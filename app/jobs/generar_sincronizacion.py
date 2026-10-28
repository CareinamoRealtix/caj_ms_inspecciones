"""Entrypoint del job de AWS Batch que genera el paquete de sincronización (HU.12).

Uso (lo invoca la job definition de Batch, misma imagen que la API):

    python -m app.jobs.generar_sincronizacion --job-id <uuid> --email <inspector>

Reutiliza `InspeccionService.get_sincronizacion()`, arma `sincronizacion.json`, lo comprime en
un .zip, lo sube a S3 y deja el estado del job en la base (`listo` o `error`).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import sys
import zipfile
from datetime import UTC, datetime

from app.application.fincas_pmtiles import (
    NOMBRE_ARCHIVO,
    NOMBRE_CAPA,
    NOMBRE_CAPA_RUTAS,
    Generador,
    generar_capa_fincas,
    generar_pmtiles,
)
from app.application.inspeccion_service import InspeccionService
from app.application.rutas_optimas import (
    ClienteOsrm,
    Origen,
    Osrm,
    RutaFecha,
    calcular_rutas,
    geojson_tramos,
    orden_por_inspeccion,
)
from app.infrastructure.clients.aws_sincronizacion import (
    ESTADO_ERROR,
    ESTADO_LISTO,
    ESTADO_PROCESANDO,
    ZipUploader,
)
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.database.connection import Database
from app.infrastructure.database.inspeccion_repository import InspeccionRepository
from app.infrastructure.database.sincronizacion_estado_repository import JobStore
from app.infrastructure.logging.config import configure_logging
from app.presentation.api.schemas.inspecciones import (
    RutaOptimaOut,
    RutaOrigenOut,
    RutaParadaOut,
    SincronizacionMapaFechaOut,
    SincronizacionMapaOut,
)

logger = logging.getLogger(__name__)

NOMBRE_JSON = "sincronizacion.json"
MENSAJE_ERROR_GENERICO = "No se pudo generar la sincronización"


def construir_zip(contenido_json: bytes, pmtiles: bytes | None = None) -> bytes:
    """Empaqueta `sincronizacion.json` (y `fincas.pmtiles`, si hay) en la raíz de un .zip."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archivo:
        archivo.writestr(NOMBRE_JSON, contenido_json)
        if pmtiles is not None:
            # El PMTiles ya viene comprimido (gzip por tesela): recomprimirlo no ahorra nada.
            archivo.writestr(NOMBRE_ARCHIVO, pmtiles, compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


def ruta_out(ruta: RutaFecha) -> RutaOptimaOut:
    return RutaOptimaOut(
        fecha=ruta.fecha,
        estado=ruta.estado,  # type: ignore[arg-type]
        motivo=ruta.motivo,
        origen=RutaOrigenOut(latitud=ruta.origen.latitud, longitud=ruta.origen.longitud),
        distancia_m=ruta.distancia_m,
        duracion_s=ruta.duracion_s,
        paradas=[
            RutaParadaOut(
                orden=p.orden,
                latitud=p.latitud,
                longitud=p.longitud,
                id_inspecciones=list(p.id_inspecciones),
                distancia_m_desde_anterior=p.distancia_m_desde_anterior,
                duracion_s_desde_anterior=p.duracion_s_desde_anterior,
                distancia_a_la_via_m=p.distancia_a_la_via_m,
            )
            for p in ruta.paradas
        ],
    )


def clave_s3(job_id: str, ahora: datetime | None = None) -> str:
    fecha = (ahora or datetime.now(UTC)).strftime("%Y-%m-%d")
    # job_id es un UUID no adivinable; no se incluye el email en la key (PII y caracteres de URL).
    return f"sincronizacion/{fecha}/{job_id}.zip"


async def generar(
    job_id: str,
    email_inspector: str,
    *,
    servicio: InspeccionService,
    store: JobStore,
    uploader: ZipUploader,
    generador_pmtiles: Generador | None = None,
    origen: Origen | None = None,
    osrm: Osrm | None = None,
) -> str:
    """Genera y sube el paquete. Devuelve la key de S3; ante error marca el job y relanza.

    Con `generador_pmtiles` agrega `fincas.pmtiles`; si esa capa falla, el paquete se sube sin ella.
    Con `origen` y `osrm` calcula una ruta óptima por fecha (`rutas_optimas` y capa `rutas`).
    """
    try:
        await store.actualizar_estado(job_id, ESTADO_PROCESANDO)
        respuesta = await servicio.get_sincronizacion(email_inspector)
        rutas = (
            await calcular_rutas(respuesta.inspecciones, origen, osrm)
            if origen is not None and osrm is not None
            else []
        )
        respuesta.rutas_optimas = [ruta_out(ruta) for ruta in rutas]
        capa = (
            await generar_capa_fincas(
                respuesta.inspecciones,
                generador=generador_pmtiles,
                rutas_geojson=geojson_tramos(rutas),
                orden_ruta=orden_por_inspeccion(rutas),
            )
            if generador_pmtiles is not None
            else None
        )
        if capa is not None:
            respuesta.meta.mapa = SincronizacionMapaOut(
                fincas_pmtiles=NOMBRE_ARCHIVO,
                capa=NOMBRE_CAPA,
                total_puntos=capa.total_puntos,
                fechas=[
                    SincronizacionMapaFechaOut(fecha=fecha, total_puntos=total)
                    for fecha, total in sorted(capa.por_fecha.items())
                ],
                capa_rutas=NOMBRE_CAPA_RUTAS if capa.con_rutas else None,
            )
        paquete = construir_zip(
            respuesta.model_dump_json().encode("utf-8"), capa.pmtiles if capa else None
        )
        s3_key = clave_s3(job_id)
        await uploader.subir(s3_key, paquete)
        await store.actualizar_estado(job_id, ESTADO_LISTO, s3_key=s3_key)
    except Exception:
        logger.exception(
            "Falló la generación de la sincronización",
            extra={"event": "sincronizacion_job_failed", "job_id": job_id},
        )
        try:
            await store.actualizar_estado(job_id, ESTADO_ERROR, error=MENSAJE_ERROR_GENERICO)
        except Exception:
            logger.exception("No se pudo registrar el error del job", extra={"job_id": job_id})
        raise
    logger.info(
        "Sincronización generada",
        extra={"event": "sincronizacion_job_done", "job_id": job_id, "bytes": len(paquete)},
    )
    return s3_key


def _generador_pmtiles(settings: Settings) -> Generador | None:
    if not settings.sincronizacion_pmtiles_habilitado:
        return None
    return lambda fincas, rutas: generar_pmtiles(
        fincas, rutas, binario=settings.sincronizacion_tippecanoe_bin
    )


async def _ejecutar(
    job_id: str, email_inspector: str, settings: Settings, origen: Origen | None = None
) -> None:
    database = Database(settings)
    osrm = (
        ClienteOsrm(settings.osrm_url, timeout=settings.osrm_timeout_segundos)
        if settings.osrm_url and origen is not None
        else None
    )
    try:
        try:
            await database.connect()
        except Exception:
            # El estado vive en la misma base: sin conexión no se puede marcar `error`. El job
            # termina con código distinto de 0 y la API lo detecta como FAILED en Batch.
            logger.exception(
                "No se pudo conectar a la base de datos",
                extra={"event": "sincronizacion_job_db_failed", "job_id": job_id},
            )
            raise
        store = JobStore(database.pool, settings)
        servicio = InspeccionService(InspeccionRepository(database.pool))
        await generar(
            job_id,
            email_inspector,
            servicio=servicio,
            store=store,
            uploader=ZipUploader(settings),
            generador_pmtiles=_generador_pmtiles(settings),
            origen=origen,
            osrm=osrm,
        )
    finally:
        await database.close()
        if osrm is not None:
            await osrm.cerrar()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera el paquete de sincronización offline")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--email", required=True)
    # Posición desde la que el inspector sincronizó: origen de las rutas óptimas (opcional).
    parser.add_argument("--origen-lat", type=float)
    parser.add_argument("--origen-lng", type=float)
    args = parser.parse_args(argv)
    if (args.origen_lat is None) != (args.origen_lng is None):
        parser.error("--origen-lat y --origen-lng van juntos")
    origen = Origen(args.origen_lat, args.origen_lng) if args.origen_lat is not None else None

    settings = get_settings()
    configure_logging(settings)
    try:
        asyncio.run(_ejecutar(args.job_id, args.email, settings, origen))
    except Exception:
        # El detalle ya se registró donde ocurrió; esto garantiza que ningún fallo salga mudo.
        logger.exception(
            "El job de sincronización terminó con error", extra={"job_id": args.job_id}
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
