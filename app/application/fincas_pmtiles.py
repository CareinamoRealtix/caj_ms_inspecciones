"""Capa de fincas (PMTiles) del paquete de sincronización (HU.11 / HU.12).

Convierte las inspecciones del paquete en un GeoJSON de puntos y lo pasa por tippecanoe para
producir `fincas.pmtiles`, que la app dibuja sobre el mapa base `panama.pmtiles` que ya tiene en
el dispositivo. Es un complemento visual: si algo falla, el paquete se genera sin la capa.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import subprocess
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.presentation.api.schemas.inspecciones import SincronizacionInspeccionOut

logger = logging.getLogger(__name__)

NOMBRE_ARCHIVO = "fincas.pmtiles"
NOMBRE_CAPA = "fincas"
NOMBRE_CAPA_RUTAS = "rutas"
ZOOM_MINIMO = 5
ZOOM_MAXIMO = 15
TIMEOUT_SEGUNDOS = 120

# Recuadro del mapa base `panama.pmtiles` (lon_min, lat_min, lon_max, lat_max). Un punto fuera de
# él se ve sobre fondo vacío y casi seguro es un error de captura, así que no se incluye.
RECUADRO_PANAMA = (-83.06, 7.03, -77.13, 9.72)

ESTADO_INSPECCION_ACTIVA = "Activa"


class PmtilesError(Exception):
    """tippecanoe no pudo generar el archivo."""


@dataclass(frozen=True)
class ResultadoGeojson:
    contenido: bytes
    total: int
    sin_coordenadas: int
    fuera_de_panama: int
    # Puntos incluidos por fecha programada: la app arma con esto el selector de fecha del mapa.
    por_fecha: dict[date, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CapaFincas:
    pmtiles: bytes
    total_puntos: int
    por_fecha: dict[date, int] = field(default_factory=dict)
    con_rutas: bool = False


def _coordenadas_validas(latitud: float | None, longitud: float | None) -> bool:
    if latitud is None or longitud is None:
        return False
    if not (math.isfinite(latitud) and math.isfinite(longitud)):
        return False
    if abs(latitud) > 90 or abs(longitud) > 180:
        return False
    return not (latitud == 0 and longitud == 0)


def _dentro_de_panama(latitud: float, longitud: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = RECUADRO_PANAMA
    return lat_min <= latitud <= lat_max and lon_min <= longitud <= lon_max


def punto_en_mapa(latitud: float | None, longitud: float | None) -> bool:
    """Coordenadas válidas y dentro del mapa base: el mismo criterio para puntos y rutas."""
    if not _coordenadas_validas(latitud, longitud):
        return False
    assert latitud is not None and longitud is not None
    return _dentro_de_panama(latitud, longitud)


def construir_geojson(
    inspecciones: Iterable[SincronizacionInspeccionOut],
    orden_ruta: Mapping[uuid.UUID, int] | None = None,
) -> ResultadoGeojson:
    """GeoJSON line-delimited (un Feature por línea) con un punto por inspección.

    Con `orden_ruta`, cada punto lleva su número de parada dentro de la ruta de su fecha.
    """
    lineas: list[str] = []
    por_fecha: Counter[date] = Counter()
    sin_coordenadas = fuera_de_panama = 0
    for inspeccion in inspecciones:
        latitud, longitud = inspeccion.finca.latitud, inspeccion.finca.longitud
        if not _coordenadas_validas(latitud, longitud):
            sin_coordenadas += 1
            continue
        assert latitud is not None and longitud is not None  # estrecha el tipo tras validar
        if not _dentro_de_panama(latitud, longitud):
            fuera_de_panama += 1
            continue
        propiedades: dict[str, object] = {
            "id_inspeccion": str(inspeccion.id_inspeccion),
            "numero_inspeccion": inspeccion.numero_inspeccion,
            "numero_finca": inspeccion.finca.numero_finca,
            "fecha_programada": inspeccion.fecha_programada.isoformat(),
            "estado": ESTADO_INSPECCION_ACTIVA,
            "asignada_al_usuario": True,
        }
        if orden_ruta and inspeccion.id_inspeccion in orden_ruta:
            propiedades["orden_ruta"] = orden_ruta[inspeccion.id_inspeccion]
        feature = {
            "type": "Feature",
            "properties": propiedades,
            # GeoJSON (RFC 7946) va en orden [longitud, latitud].
            "geometry": {"type": "Point", "coordinates": [longitud, latitud]},
        }
        lineas.append(json.dumps(feature, ensure_ascii=False, separators=(",", ":")))
        por_fecha[inspeccion.fecha_programada] += 1
    contenido = ("\n".join(lineas) + "\n").encode("utf-8") if lineas else b""
    return ResultadoGeojson(
        contenido, len(lineas), sin_coordenadas, fuera_de_panama, dict(sorted(por_fecha.items()))
    )


Ejecutor = Callable[..., "subprocess.CompletedProcess[bytes]"]


def generar_pmtiles(
    geojson: bytes,
    rutas_geojson: bytes | None = None,
    *,
    binario: str = "tippecanoe",
    timeout: int = TIMEOUT_SEGUNDOS,
    ejecutar: Ejecutor = subprocess.run,
) -> bytes:
    """Ejecuta tippecanoe y devuelve el contenido de `fincas.pmtiles`.

    Capa `fincas` con los puntos y, si llega `rutas_geojson`, capa `rutas` con las líneas, en el
    mismo archivo.
    """
    with tempfile.TemporaryDirectory(prefix="fincas-pmtiles-") as carpeta:
        entrada = Path(carpeta) / "fincas.geojsonl"
        salida = Path(carpeta) / NOMBRE_ARCHIVO
        entrada.write_bytes(geojson)
        capas = ["-L", f"{NOMBRE_CAPA}:{entrada}"]
        if rutas_geojson:
            entrada_rutas = Path(carpeta) / "rutas.geojsonl"
            entrada_rutas.write_bytes(rutas_geojson)
            capas += ["-L", f"{NOMBRE_CAPA_RUTAS}:{entrada_rutas}"]
        comando = [
            binario,
            "-q",
            "-o", str(salida),
            "-Z", str(ZOOM_MINIMO),
            "-z", str(ZOOM_MAXIMO),
            # Son pocos puntos y todos deben verse: sin descartar ni agrupar.
            "-r1",
            "--no-feature-limit",
            "--no-tile-size-limit",
            "--force",
            *capas,
        ]  # fmt: skip
        try:
            resultado = ejecutar(comando, capture_output=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise PmtilesError(f"no se encontró el binario {binario!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PmtilesError(f"tippecanoe superó los {timeout} s") from exc
        if resultado.returncode != 0:
            detalle = (resultado.stderr or b"").decode("utf-8", "replace").strip()[-500:]
            raise PmtilesError(f"tippecanoe terminó con código {resultado.returncode}: {detalle}")
        if not salida.is_file() or salida.stat().st_size == 0:
            raise PmtilesError("tippecanoe no produjo el archivo")
        return salida.read_bytes()


# (geojson de fincas, geojson de rutas o None) -> contenido del .pmtiles
Generador = Callable[[bytes, bytes | None], bytes]


async def generar_capa_fincas(
    inspecciones: Iterable[SincronizacionInspeccionOut],
    *,
    generador: Generador = generar_pmtiles,
    rutas_geojson: bytes | None = None,
    orden_ruta: Mapping[uuid.UUID, int] | None = None,
) -> CapaFincas | None:
    """Devuelve la capa, o None si no hay puntos o si falló. Nunca lanza."""
    try:
        geojson = construir_geojson(inspecciones, orden_ruta)
        if geojson.sin_coordenadas or geojson.fuera_de_panama:
            logger.warning(
                "Inspecciones omitidas de la capa de fincas",
                extra={
                    "event": "pmtiles_puntos_omitidos",
                    "sin_coordenadas": geojson.sin_coordenadas,
                    "fuera_de_panama": geojson.fuera_de_panama,
                },
            )
        if geojson.total == 0:
            return None
        # tippecanoe es bloqueante: se saca del event loop.
        rutas = rutas_geojson or None
        contenido = await asyncio.to_thread(generador, geojson.contenido, rutas)
        return CapaFincas(contenido, geojson.total, geojson.por_fecha, con_rutas=rutas is not None)
    except Exception:
        logger.exception(
            "No se pudo generar fincas.pmtiles; el paquete sigue sin la capa",
            extra={"event": "pmtiles_failed"},
        )
        return None
