"""Entrypoint del job de AWS Batch que procesa un ZIP de levantamientos subido por la app (HU.12).

Uso (lo invoca la job definition de Batch, misma imagen que la API):

    python -m app.jobs.procesar_subida --subida-id <uuid> --email <inspector>

Descarga el .zip del bucket temporal, valida su contenido, sube las imágenes al bucket de fotos y
finaliza cada levantamiento con la misma lógica de `POST /levantamiento/batch`. El resultado por
inspección queda en la base. Un levantamiento inválido no aborta el resto.

El ZIP nunca se extrae a disco: se leen solo las entradas que el JSON referencia, así el nombre de
una entrada jamás se usa como ruta de archivo ni como key de S3 (no hay "Zip Slip").
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.application.inspeccion_service import InspeccionService
from app.infrastructure.clients.aws_subida import (
    ESTADO_ERROR,
    ESTADO_LISTO,
    ESTADO_PARCIAL,
    ESTADO_PROCESANDO,
    SubidaS3,
)
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.database.connection import Database
from app.infrastructure.database.inspeccion_repository import InspeccionRepository
from app.infrastructure.database.sincronizacion_estado_repository import SubidaStore
from app.infrastructure.logging.config import configure_logging
from app.presentation.api.schemas.inspecciones import (
    LevantamientoBatchItemRequest,
    LevantamientoBatchRequest,
)

logger = logging.getLogger(__name__)

NOMBRE_MANIFEST = "manifest.json"
NOMBRE_LEVANTAMIENTOS = "levantamientos.json"
VERSION_FORMATO = 1
MENSAJE_ERROR_GENERICO = "No se pudo procesar la subida"
MENSAJE_ZIP_INVALIDO = "El archivo de sincronización no es válido"
MAX_BYTES_JSON = 20 * 1024 * 1024

# Tipos aceptados, identificados por contenido (no por extensión).
FIRMAS_IMAGEN = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


class ZipInvalidoError(Exception):
    """El ZIP no cumple el formato esperado; ningún levantamiento se procesa."""


@dataclass(frozen=True)
class Imagen:
    contenido: bytes
    content_type: str
    extension: str


def detectar_imagen(contenido: bytes) -> Imagen | None:
    for firma, content_type, extension in FIRMAS_IMAGEN:
        if contenido.startswith(firma):
            return Imagen(contenido, content_type, extension)
    return None


def _ruta_segura(nombre: str) -> bool:
    """Rechaza rutas absolutas, con `..`, con `\\` o con caracteres de control."""
    if not nombre or nombre.startswith("/") or "\\" in nombre:
        return False
    if any(ord(c) < 32 for c in nombre):
        return False
    return ".." not in nombre.split("/")


class PaqueteSubida:
    """Lectura validada del ZIP: solo se abre lo que el JSON referencia."""

    def __init__(self, archivo: zipfile.ZipFile, settings: Settings) -> None:
        self._zip = archivo
        self._cfg = settings
        self._nombres = {i.filename: i for i in archivo.infolist() if not i.is_dir()}

    def validar_estructura(self) -> None:
        if len(self._nombres) > self._cfg.subida_max_levantamientos * (
            self._cfg.subida_max_fotos_por_levantamiento + 2
        ):
            raise ZipInvalidoError("demasiadas entradas")
        for nombre in self._nombres:
            if not _ruta_segura(nombre):
                raise ZipInvalidoError("ruta de entrada no permitida")
        if NOMBRE_MANIFEST not in self._nombres or NOMBRE_LEVANTAMIENTOS not in self._nombres:
            raise ZipInvalidoError("faltan manifest.json o levantamientos.json")

    def existe(self, nombre: str) -> bool:
        return nombre in self._nombres

    def leer(self, nombre: str, maximo: int) -> bytes:
        info = self._nombres.get(nombre)
        if info is None:
            raise ZipInvalidoError(f"falta el archivo {nombre}")
        # No se confía en `file_size`: se lee con tope y se compara contra lo realmente leído.
        with self._zip.open(info) as f:
            contenido = f.read(maximo + 1)
        if len(contenido) > maximo:
            raise ZipInvalidoError(f"{nombre} supera el tamaño máximo")
        return contenido

    def leer_json(self, nombre: str) -> Any:
        try:
            return json.loads(self.leer(nombre, MAX_BYTES_JSON))
        except json.JSONDecodeError as exc:
            raise ZipInvalidoError(f"{nombre} no es JSON válido") from exc


def preparar_items(paquete: PaqueteSubida, settings: Settings) -> list[dict[str, Any]]:
    """Valida manifest y JSON. Devuelve los ítems crudos; no escribe nada."""
    manifest = paquete.leer_json(NOMBRE_MANIFEST)
    if not isinstance(manifest, dict) or manifest.get("version") != VERSION_FORMATO:
        raise ZipInvalidoError("versión de formato no soportada")
    levantamientos = paquete.leer_json(NOMBRE_LEVANTAMIENTOS)
    if isinstance(levantamientos, dict):
        levantamientos = levantamientos.get("levantamientos")
    if not isinstance(levantamientos, list) or not levantamientos:
        raise ZipInvalidoError("levantamientos.json no contiene levantamientos")
    if len(levantamientos) > settings.subida_max_levantamientos:
        raise ZipInvalidoError("demasiados levantamientos")
    if manifest.get("cantidad_levantamientos") != len(levantamientos):
        raise ZipInvalidoError("la cantidad del manifest no coincide")
    if not all(isinstance(i, dict) for i in levantamientos):
        raise ZipInvalidoError("levantamientos.json tiene un formato inválido")
    return levantamientos  # type: ignore[no-any-return]


def _resultado_error(id_inspeccion: str, codigo: str) -> dict[str, Any]:
    return {"id_inspeccion": id_inspeccion, "exito": False, "codigo_error": codigo}


async def procesar_item(
    crudo: dict[str, Any],
    *,
    paquete: PaqueteSubida,
    servicio: InspeccionService,
    s3: SubidaS3,
    settings: Settings,
    usuario: str,
) -> dict[str, Any]:
    """Sube las imágenes de un levantamiento y lo finaliza. Devuelve su resultado."""
    id_inspeccion = str(crudo.get("id_inspeccion", ""))
    try:
        id_op = str(uuid.UUID(str(crudo.get("id_operacion"))))
        fotos = crudo.get("fotografias") or []
        if not isinstance(fotos, list) or len(fotos) > settings.subida_max_fotos_por_levantamiento:
            return _resultado_error(id_inspeccion, "datos_invalidos")
        rutas = [str(f.get("archivo", "")) for f in fotos if isinstance(f, dict)]
        ruta_firma = crudo.get("archivo_firma")
        if len(rutas) != len(fotos) or not all(paquete.existe(r) for r in rutas):
            return _resultado_error(id_inspeccion, "archivo_faltante")
        if ruta_firma and not paquete.existe(str(ruta_firma)):
            return _resultado_error(id_inspeccion, "archivo_faltante")

        # Se leen y validan TODAS las imágenes antes de subir ninguna.
        maximo = settings.subida_max_bytes_por_imagen
        imagenes: list[Imagen] = []
        firma: Imagen | None = None
        try:
            for ruta in rutas:
                imagen = detectar_imagen(paquete.leer(ruta, maximo))
                if imagen is None:
                    return _resultado_error(id_inspeccion, "imagen_invalida")
                imagenes.append(imagen)
            if ruta_firma:
                firma = detectar_imagen(paquete.leer(str(ruta_firma), maximo))
                if firma is None:
                    return _resultado_error(id_inspeccion, "imagen_invalida")
        except ZipInvalidoError:  # supera el tamaño máximo por imagen
            return _resultado_error(id_inspeccion, "imagen_invalida")

        datos = {k: v for k, v in crudo.items() if k not in ("archivo_firma", "fotografias")}
        datos["fotografias"] = []
        for n, (foto, imagen) in enumerate(zip(fotos, imagenes, strict=True), start=1):
            # Key determinística: reintentar el job sobrescribe el mismo objeto, no duplica.
            clave = f"fotos/{id_inspeccion}/{id_op}/{n:04d}.{imagen.extension}"
            datos["fotografias"].append(
                {
                    **{k: v for k, v in foto.items() if k != "archivo"},
                    "url": clave,
                }
            )
        if firma is not None:
            clave_firma = f"firmas/{id_inspeccion}/{id_op}.{firma.extension}"
            datos["url_firma_inspector"] = clave_firma

        item = LevantamientoBatchItemRequest(**datos)
        # Solo después de validar el levantamiento completo se escribe en el bucket de fotos.
        for n, imagen in enumerate(imagenes, start=1):
            await s3.subir_imagen(
                f"fotos/{id_inspeccion}/{id_op}/{n:04d}.{imagen.extension}",
                imagen.contenido,
                imagen.content_type,
            )
        if firma is not None:
            await s3.subir_imagen(
                f"firmas/{id_inspeccion}/{id_op}.{firma.extension}",
                firma.contenido,
                firma.content_type,
            )
    except (ValidationError, ValueError, ZipInvalidoError):
        return _resultado_error(id_inspeccion, "datos_invalidos")

    respuesta = await servicio.finalizar_levantamiento_batch(
        LevantamientoBatchRequest(levantamientos=[item]), usuario=usuario
    )
    r = respuesta.resultados[0]
    return {
        "id_inspeccion": str(r.id_inspeccion),
        "exito": r.exito,
        "repetido": r.repetido,
        "id_levantamiento": str(r.id_levantamiento) if r.id_levantamiento else None,
        "codigo_error": r.codigo_error,
        "mensaje": r.mensaje,
    }


async def procesar(
    subida_id: str,
    email_inspector: str,
    *,
    servicio: InspeccionService,
    store: SubidaStore,
    s3: SubidaS3,
    settings: Settings,
) -> str:
    """Procesa la subida. Devuelve el estado final; ante error inesperado lo marca y relanza."""
    try:
        subida = await store.obtener(subida_id)
        if subida is None or subida.email_inspector != email_inspector:
            raise ZipInvalidoError("subida inexistente o de otro inspector")
        await store.actualizar_estado(subida_id, ESTADO_PROCESANDO, reiniciar_resultados=True)

        with tempfile.TemporaryFile() as temporal:
            await s3.descargar_zip(subida.s3_key, temporal)
            temporal.seek(0)
            sha = hashlib.sha256()
            while bloque := temporal.read(1024 * 1024):
                sha.update(bloque)
            if sha.hexdigest() != subida.sha256:
                raise ZipInvalidoError("el sha256 no coincide con el declarado")
            temporal.seek(0)
            try:
                archivo = zipfile.ZipFile(temporal)
            except zipfile.BadZipFile as exc:
                raise ZipInvalidoError("no es un ZIP válido") from exc
            with archivo:
                paquete = PaqueteSubida(archivo, settings)
                paquete.validar_estructura()
                items = preparar_items(paquete, settings)
                if len(items) != subida.cantidad_levantamientos:
                    raise ZipInvalidoError("la cantidad declarada al crear la subida no coincide")
                exitosos = 0
                for crudo in items:
                    resultado = await procesar_item(
                        crudo,
                        paquete=paquete,
                        servicio=servicio,
                        s3=s3,
                        settings=settings,
                        usuario=email_inspector,
                    )
                    exitosos += 1 if resultado["exito"] else 0
                    await store.agregar_resultado(subida_id, resultado)

        estado = ESTADO_LISTO if exitosos == len(items) else ESTADO_PARCIAL
        await store.actualizar_estado(subida_id, estado)
    except ZipInvalidoError as exc:
        logger.warning(
            "ZIP de subida rechazado",
            extra={"event": "subida_zip_invalido", "subida_id": subida_id, "motivo": str(exc)},
        )
        await store.actualizar_estado(subida_id, ESTADO_ERROR, error=MENSAJE_ZIP_INVALIDO)
        return ESTADO_ERROR
    except Exception:
        logger.exception(
            "Falló el procesamiento de la subida",
            extra={"event": "subida_job_failed", "subida_id": subida_id},
        )
        try:
            await store.actualizar_estado(subida_id, ESTADO_ERROR, error=MENSAJE_ERROR_GENERICO)
        except Exception:
            logger.exception(
                "No se pudo registrar el error de la subida", extra={"subida_id": subida_id}
            )
        raise
    logger.info(
        "Subida procesada",
        extra={"event": "subida_job_done", "subida_id": subida_id, "estado": estado},
    )
    return estado


async def _ejecutar(subida_id: str, email_inspector: str, settings: Settings) -> None:
    database = Database(settings)
    try:
        try:
            await database.connect()
        except Exception:
            logger.exception(
                "No se pudo conectar a la base de datos",
                extra={"event": "subida_job_db_failed", "subida_id": subida_id},
            )
            # El estado vive en la misma base: sin conexión no se puede marcar `error`. El job
            # termina con código distinto de 0 y la API lo detecta como FAILED en Batch.
            raise
        store = SubidaStore(database.pool, settings)
        servicio = InspeccionService(InspeccionRepository(database.pool))
        await procesar(
            subida_id,
            email_inspector,
            servicio=servicio,
            store=store,
            s3=SubidaS3(settings),
            settings=settings,
        )
    finally:
        await database.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Procesa un ZIP de levantamientos subido")
    parser.add_argument("--subida-id", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings)
    try:
        asyncio.run(_ejecutar(args.subida_id, args.email, settings))
    except Exception:
        logger.exception("El job de subida terminó con error", extra={"subida_id": args.subida_id})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
