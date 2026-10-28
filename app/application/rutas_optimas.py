"""Rutas óptimas por fecha (OSRM) para el paquete de sincronización.

Para cada fecha del paquete agrupa las fincas por ubicación, decide el orden de visita saliendo del
punto desde el que el inspector sincronizó (viaje abierto: no vuelve al inicio) y pide a OSRM la
ruta por calles en ese orden. Todas las fechas salen del mismo origen. Es un complemento: ante
cualquier falla la fecha queda `sin_ruta` con su motivo y el paquete se genera igual.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import httpx

from app.application.fincas_pmtiles import punto_en_mapa
from app.presentation.api.schemas.inspecciones import SincronizacionInspeccionOut

logger = logging.getLogger(__name__)


ESTADO_OK = "ok"
ESTADO_SIN_RUTA = "sin_ruta"
MOTIVO_ORIGEN_FUERA_DE_PANAMA = "origen_fuera_de_panama"
MOTIVO_OSRM_NO_DISPONIBLE = "osrm_no_disponible"
MOTIVO_SIN_RUTA_VIAL = "sin_ruta_vial"

MAX_PASADAS_2OPT = 50

Punto = tuple[float, float]  # (latitud, longitud)


class OsrmError(Exception):
    """OSRM no respondió o respondió con un error."""


class SinRutaVialError(OsrmError):
    """OSRM no encontró camino por calles entre los puntos (NoRoute / NoSegment)."""


@dataclass(frozen=True)
class Origen:
    latitud: float
    longitud: float


@dataclass(frozen=True)
class Parada:
    orden: int
    latitud: float
    longitud: float
    id_inspecciones: tuple[uuid.UUID, ...]
    distancia_m_desde_anterior: int
    duracion_s_desde_anterior: int
    distancia_a_la_via_m: int


@dataclass(frozen=True)
class Tramo:
    tramo: int
    orden_desde: int  # 0 = origen
    orden_hasta: int
    distancia_m: int
    duracion_s: int
    coordenadas: tuple[tuple[float, float], ...]  # [longitud, latitud], como GeoJSON


@dataclass(frozen=True)
class RutaFecha:
    fecha: date
    origen: Origen
    estado: str
    motivo: str | None = None
    distancia_m: int | None = None
    duracion_s: int | None = None
    paradas: tuple[Parada, ...] = ()
    tramos: tuple[Tramo, ...] = ()


class Osrm(Protocol):
    async def duraciones(self, puntos: Sequence[Punto]) -> list[list[float | None]]: ...

    async def ruta(self, puntos: Sequence[Punto]) -> dict[str, Any]: ...


class ClienteOsrm:
    """Cliente HTTP mínimo de `osrm-routed` (perfil auto)."""

    def __init__(
        self, base_url: str, *, timeout: float = 10.0, http: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def _consultar(
        self, servicio: str, puntos: Sequence[Punto], params: dict[str, str]
    ) -> dict[str, Any]:
        # OSRM recibe las coordenadas en orden longitud,latitud.
        coordenadas = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in puntos)
        url = f"{self._base_url}/{servicio}/v1/driving/{coordenadas}"
        try:
            respuesta = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise OsrmError(f"no se pudo consultar OSRM: {exc.__class__.__name__}") from exc
        try:
            cuerpo: dict[str, Any] = respuesta.json()
        except ValueError as exc:
            raise OsrmError(f"respuesta no JSON (HTTP {respuesta.status_code})") from exc
        codigo = cuerpo.get("code")
        if codigo in ("NoRoute", "NoSegment"):
            raise SinRutaVialError(str(codigo))
        if respuesta.status_code != 200 or codigo != "Ok":
            raise OsrmError(f"HTTP {respuesta.status_code}, código {codigo}")
        return cuerpo

    async def duraciones(self, puntos: Sequence[Punto]) -> list[list[float | None]]:
        """Matriz de duraciones en segundos (`None` = sin camino entre ese par)."""
        cuerpo = await self._consultar("table", puntos, {})
        return cuerpo["durations"]  # type: ignore[no-any-return]

    async def ruta(self, puntos: Sequence[Punto]) -> dict[str, Any]:
        """Ruta por calles que pasa por los puntos en el orden dado.

        `steps=true` solo se pide para obtener la geometría de cada tramo; las instrucciones de
        giro no se usan.
        """
        params = {"overview": "false", "steps": "true", "geometries": "geojson"}
        return await self._consultar("route", puntos, params)

    async def cerrar(self) -> None:
        await self._http.aclose()


def ordenar_paradas(duraciones: Sequence[Sequence[float | None]]) -> list[int]:
    """Orden de visita de los índices 1..n saliendo del 0, sin volver (viaje abierto).

    Vecino más cercano y luego mejora 2-opt. La matriz puede ser asimétrica (calles de un solo
    sentido), así que al invertir un segmento se recalculan sus tramos internos en sentido inverso.
    """
    n = len(duraciones)

    def d(i: int, j: int) -> float:
        valor = duraciones[i][j]
        return math.inf if valor is None else float(valor)

    pendientes = set(range(1, n))
    camino = [0]
    while pendientes:
        ultimo = camino[-1]
        siguiente = min(pendientes, key=lambda j: (d(ultimo, j), j))
        camino.append(siguiente)
        pendientes.remove(siguiente)

    for _ in range(MAX_PASADAS_2OPT):
        mejoro = False
        for i in range(1, n - 1):
            # Invertir camino[i..k]; ida y vuelta del segmento se acumulan para no recorrerlo.
            ida = vuelta = 0.0
            for k in range(i + 1, n):
                ida += d(camino[k - 1], camino[k])
                vuelta += d(camino[k], camino[k - 1])
                antes, primero, ultimo = camino[i - 1], camino[i], camino[k]
                cola = k + 1 < n  # si el segmento llega al final, no hay tramo de salida
                actual = d(antes, primero) + ida + (d(ultimo, camino[k + 1]) if cola else 0.0)
                nuevo = d(antes, ultimo) + vuelta + (d(primero, camino[k + 1]) if cola else 0.0)
                if nuevo < actual - 1e-9:
                    camino[i : k + 1] = reversed(camino[i : k + 1])
                    mejoro = True
                    break
        if not mejoro:
            break
    return camino[1:]


def _agrupar_por_fecha(
    inspecciones: Iterable[SincronizacionInspeccionOut],
) -> dict[date, dict[Punto, list[uuid.UUID]]]:
    """Fecha → ubicación → inspecciones. Varias inspecciones en el mismo punto son una parada."""
    por_fecha: dict[date, dict[Punto, list[uuid.UUID]]] = {}
    for inspeccion in inspecciones:
        latitud, longitud = inspeccion.finca.latitud, inspeccion.finca.longitud
        if not punto_en_mapa(latitud, longitud):
            continue
        assert latitud is not None and longitud is not None  # estrecha el tipo tras validar
        ubicacion = (round(latitud, 6), round(longitud, 6))
        paradas = por_fecha.setdefault(inspeccion.fecha_programada, {})
        paradas.setdefault(ubicacion, []).append(inspeccion.id_inspeccion)
    return por_fecha


def _geometria_tramo(leg: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    coordenadas: list[tuple[float, float]] = []
    for paso in leg.get("steps", []):
        for lng, lat in paso["geometry"]["coordinates"]:
            punto = (lng, lat)
            if not coordenadas or coordenadas[-1] != punto:
                coordenadas.append(punto)
    return tuple(coordenadas)


async def _ruta_de_fecha(
    fecha: date, origen: Origen, ubicaciones: dict[Punto, list[uuid.UUID]], osrm: Osrm
) -> RutaFecha:
    paradas_sin_orden = list(ubicaciones.items())
    puntos: list[Punto] = [(origen.latitud, origen.longitud)] + [p for p, _ in paradas_sin_orden]

    matriz = await osrm.duraciones(puntos)
    orden = ordenar_paradas(matriz)
    if any(matriz[a][b] is None for a, b in zip([0, *orden], orden, strict=False)):
        return RutaFecha(fecha, origen, ESTADO_SIN_RUTA, MOTIVO_SIN_RUTA_VIAL)

    cuerpo = await osrm.ruta([puntos[0]] + [puntos[i] for i in orden])
    ruta = cuerpo["routes"][0]
    waypoints = cuerpo["waypoints"]
    paradas: list[Parada] = []
    tramos: list[Tramo] = []
    for numero, (indice, leg) in enumerate(zip(orden, ruta["legs"], strict=True), start=1):
        (latitud, longitud), ids = paradas_sin_orden[indice - 1]
        distancia, duracion = round(leg["distance"]), round(leg["duration"])
        paradas.append(
            Parada(
                orden=numero,
                latitud=latitud,
                longitud=longitud,
                id_inspecciones=tuple(ids),
                distancia_m_desde_anterior=distancia,
                duracion_s_desde_anterior=duracion,
                distancia_a_la_via_m=round(waypoints[numero].get("distance", 0)),
            )
        )
        geometria = _geometria_tramo(leg)
        if len(geometria) >= 2:  # origen y parada en el mismo punto: no hay línea que dibujar
            tramos.append(Tramo(numero, numero - 1, numero, distancia, duracion, geometria))
    return RutaFecha(
        fecha,
        origen,
        ESTADO_OK,
        distancia_m=round(ruta["distance"]),
        duracion_s=round(ruta["duration"]),
        paradas=tuple(paradas),
        tramos=tuple(tramos),
    )


async def calcular_rutas(
    inspecciones: Iterable[SincronizacionInspeccionOut], origen: Origen, osrm: Osrm
) -> list[RutaFecha]:
    """Una ruta por fecha con fincas ubicadas, ordenadas por fecha. Nunca lanza."""
    por_fecha = _agrupar_por_fecha(inspecciones)
    origen_valido = punto_en_mapa(origen.latitud, origen.longitud)
    rutas: list[RutaFecha] = []
    for fecha in sorted(por_fecha):
        if not origen_valido:
            rutas.append(RutaFecha(fecha, origen, ESTADO_SIN_RUTA, MOTIVO_ORIGEN_FUERA_DE_PANAMA))
            continue
        try:
            rutas.append(await _ruta_de_fecha(fecha, origen, por_fecha[fecha], osrm))
        except SinRutaVialError:
            rutas.append(RutaFecha(fecha, origen, ESTADO_SIN_RUTA, MOTIVO_SIN_RUTA_VIAL))
        except Exception:
            logger.exception(
                "No se pudo calcular la ruta óptima de una fecha",
                extra={"event": "ruta_optima_failed", "fecha": fecha.isoformat()},
            )
            rutas.append(RutaFecha(fecha, origen, ESTADO_SIN_RUTA, MOTIVO_OSRM_NO_DISPONIBLE))
    return rutas


def orden_por_inspeccion(rutas: Iterable[RutaFecha]) -> dict[uuid.UUID, int]:
    """Número de parada de cada inspección (atributo `orden_ruta` de la capa de fincas)."""
    return {
        id_inspeccion: parada.orden
        for ruta in rutas
        for parada in ruta.paradas
        for id_inspeccion in parada.id_inspecciones
    }


def geojson_tramos(rutas: Iterable[RutaFecha]) -> bytes:
    """GeoJSON line-delimited con un LineString por tramo (capa `rutas` del PMTiles)."""
    lineas: list[str] = []
    for ruta in rutas:
        for tramo in ruta.tramos:
            feature = {
                "type": "Feature",
                "properties": {
                    "fecha_programada": ruta.fecha.isoformat(),
                    "tramo": tramo.tramo,
                    "orden_desde": tramo.orden_desde,
                    "orden_hasta": tramo.orden_hasta,
                    "distancia_m": tramo.distancia_m,
                    "duracion_s": tramo.duracion_s,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(punto) for punto in tramo.coordenadas],
                },
            }
            lineas.append(json.dumps(feature, separators=(",", ":")))
    return ("\n".join(lineas) + "\n").encode("utf-8") if lineas else b""
