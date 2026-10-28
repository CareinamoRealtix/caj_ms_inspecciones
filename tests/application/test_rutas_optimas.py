import itertools
import json
import os
import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.application.rutas_optimas import (
    ClienteOsrm,
    Origen,
    OsrmError,
    SinRutaVialError,
    calcular_rutas,
    geojson_tramos,
    orden_por_inspeccion,
    ordenar_paradas,
)

HOY, MANANA = date(2026, 11, 17), date(2026, 11, 18)
ORIGEN = Origen(8.968, -79.539)  # Calidonia, Ciudad de Panamá


def _inspeccion(lat: float | None, lng: float | None, fecha: date = HOY) -> Any:
    return SimpleNamespace(
        id_inspeccion=uuid.uuid4(),
        fecha_programada=fecha,
        finca=SimpleNamespace(latitud=lat, longitud=lng),
    )


def _costo(matriz: list[list[float]], orden: list[int]) -> float:
    camino = [0, *orden]
    return sum(matriz[a][b] for a, b in itertools.pairwise(camino))


# --- ordenar_paradas -------------------------------------------------------------------------


def test_orden_sobre_una_recta_va_del_mas_cercano_al_mas_lejano() -> None:
    posiciones = [0, 3, 1, 4, 2]  # origen en 0; paradas desordenadas sobre una línea
    matriz = [[abs(a - b) for b in posiciones] for a in posiciones]

    assert ordenar_paradas(matriz) == [2, 4, 1, 3]


def test_orden_es_viaje_abierto_no_vuelve_al_origen() -> None:
    # Ir lejos primero y volver es más corto en circuito, pero en viaje abierto conviene
    # terminar en la más lejana.
    posiciones = [0, 10, 1]
    matriz = [[abs(a - b) for b in posiciones] for a in posiciones]

    assert ordenar_paradas(matriz) == [2, 1]


def test_2opt_corrige_al_vecino_mas_cercano() -> None:
    # Puntos en el plano donde el vecino más cercano se equivoca.
    puntos = [(0, 0), (1, 0), (-1.1, 0), (2.5, 0), (-3, 0)]
    matriz = [[abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in puntos] for a in puntos]

    orden = ordenar_paradas(matriz)

    mejor = min(_costo(matriz, list(p)) for p in itertools.permutations(range(1, 5)))
    assert _costo(matriz, orden) == pytest.approx(mejor)


def test_orden_respeta_matriz_asimetrica() -> None:
    # 1→2 es barato pero 2→1 caro (calle de un solo sentido).
    matriz = [
        [0, 5, 5],
        [5, 0, 1],
        [5, 50, 0],
    ]
    assert ordenar_paradas(matriz) == [1, 2]


def test_orden_trata_none_como_inalcanzable() -> None:
    matriz: list[list[float | None]] = [[0, None, 2], [None, 0, 1], [2, 1, 0]]
    assert ordenar_paradas(matriz) == [2, 1]


def test_orden_con_una_sola_parada_y_sin_paradas() -> None:
    assert ordenar_paradas([[0, 4], [4, 0]]) == [1]
    assert ordenar_paradas([[0]]) == []


# --- calcular_rutas con OSRM falso ---------------------------------------------------------


class FakeOsrm:
    """Duraciones = distancia en grados por 1000; la ruta es la recta entre puntos."""

    def __init__(self, error: Exception | None = None, sin_camino: bool = False) -> None:
        self.error, self.sin_camino = error, sin_camino
        self.rutas_pedidas: list[list[tuple[float, float]]] = []

    async def duraciones(self, puntos: list[tuple[float, float]]) -> list[list[float | None]]:
        if self.error:
            raise self.error
        matriz: list[list[float | None]] = [
            [abs(a[0] - b[0]) * 1000 + abs(a[1] - b[1]) * 1000 for b in puntos] for a in puntos
        ]
        if self.sin_camino:
            matriz[0] = [0] + [None] * (len(puntos) - 1)
        return matriz

    async def ruta(self, puntos: list[tuple[float, float]]) -> dict[str, Any]:
        self.rutas_pedidas.append(list(puntos))
        legs = []
        for (la1, ln1), (la2, ln2) in itertools.pairwise(puntos):
            legs.append(
                {
                    "distance": 100.4,
                    "duration": 20.6,
                    "steps": [
                        {"geometry": {"coordinates": [[ln1, la1], [ln2, la2]]}},
                        {"geometry": {"coordinates": [[ln2, la2], [ln2, la2]]}},  # "arrive"
                    ],
                }
            )
        return {
            "routes": [{"distance": 100.4 * len(legs), "duration": 20.6 * len(legs), "legs": legs}],
            "waypoints": [{"distance": 7.2} for _ in puntos],
        }


async def test_una_ruta_por_fecha_desde_el_mismo_origen() -> None:
    cerca, lejos = _inspeccion(8.970, -79.539), _inspeccion(8.990, -79.539)
    otra_fecha = _inspeccion(8.980, -79.530, MANANA)
    osrm = FakeOsrm()

    rutas = await calcular_rutas([lejos, otra_fecha, cerca], ORIGEN, osrm)

    assert [r.fecha for r in rutas] == [HOY, MANANA]
    assert all(r.origen == ORIGEN and r.estado == "ok" for r in rutas)
    hoy = rutas[0]
    assert [p.id_inspecciones for p in hoy.paradas] == [
        (cerca.id_inspeccion,),
        (lejos.id_inspeccion,),
    ]
    assert [p.orden for p in hoy.paradas] == [1, 2]
    assert (hoy.distancia_m, hoy.duracion_s) == (201, 41)
    assert hoy.paradas[0].distancia_a_la_via_m == 7
    # Cada ruta pedida a OSRM empieza en el origen.
    assert all(r[0] == (ORIGEN.latitud, ORIGEN.longitud) for r in osrm.rutas_pedidas)


async def test_tramos_encadenados_desde_el_origen() -> None:
    a, b = _inspeccion(8.970, -79.539), _inspeccion(8.990, -79.539)

    (ruta,) = await calcular_rutas([a, b], ORIGEN, FakeOsrm())

    assert [(t.tramo, t.orden_desde, t.orden_hasta) for t in ruta.tramos] == [(1, 0, 1), (2, 1, 2)]
    # Sin puntos repetidos al unir los pasos; el tramo 2 empieza donde termina el 1.
    assert ruta.tramos[0].coordenadas == ((-79.539, 8.968), (-79.539, 8.970))
    assert ruta.tramos[1].coordenadas[0] == ruta.tramos[0].coordenadas[-1]


async def test_inspecciones_en_el_mismo_punto_son_una_parada() -> None:
    a, b = _inspeccion(8.98, -79.52), _inspeccion(8.98, -79.52)

    (ruta,) = await calcular_rutas([a, b], ORIGEN, FakeOsrm())

    assert len(ruta.paradas) == 1
    assert set(ruta.paradas[0].id_inspecciones) == {a.id_inspeccion, b.id_inspeccion}


async def test_ignora_fincas_sin_coordenadas_o_fuera_de_panama() -> None:
    rutas = await calcular_rutas(
        [_inspeccion(None, None), _inspeccion(3.0, -79.5), _inspeccion(8.98, -79.52, MANANA)],
        ORIGEN,
        FakeOsrm(),
    )
    assert [r.fecha for r in rutas] == [MANANA]


async def test_origen_fuera_de_panama_deja_cada_fecha_sin_ruta() -> None:
    osrm = FakeOsrm()

    rutas = await calcular_rutas([_inspeccion(8.98, -79.52)], Origen(4.6, -74.08), osrm)

    assert [(r.estado, r.motivo) for r in rutas] == [("sin_ruta", "origen_fuera_de_panama")]
    assert osrm.rutas_pedidas == []


@pytest.mark.parametrize(
    ("osrm", "motivo"),
    [
        (FakeOsrm(error=OsrmError("caído")), "osrm_no_disponible"),
        (FakeOsrm(error=RuntimeError("inesperado")), "osrm_no_disponible"),
        (FakeOsrm(error=SinRutaVialError("NoRoute")), "sin_ruta_vial"),
        (FakeOsrm(sin_camino=True), "sin_ruta_vial"),
    ],
)
async def test_falla_de_osrm_deja_la_fecha_sin_ruta_sin_lanzar(osrm: FakeOsrm, motivo: str) -> None:
    (ruta,) = await calcular_rutas([_inspeccion(8.98, -79.52)], ORIGEN, osrm)

    assert (ruta.estado, ruta.motivo, ruta.paradas, ruta.tramos) == ("sin_ruta", motivo, (), ())


async def test_orden_por_inspeccion_y_geojson_de_tramos() -> None:
    a, b = _inspeccion(8.970, -79.539), _inspeccion(8.990, -79.539)
    rutas = await calcular_rutas([a, b], ORIGEN, FakeOsrm())

    assert orden_por_inspeccion(rutas) == {a.id_inspeccion: 1, b.id_inspeccion: 2}
    features = [json.loads(linea) for linea in geojson_tramos(rutas).decode().splitlines()]
    assert [f["geometry"]["type"] for f in features] == ["LineString", "LineString"]
    assert features[0]["properties"] == {
        "fecha_programada": "2026-11-17",
        "tramo": 1,
        "orden_desde": 0,
        "orden_hasta": 1,
        "distancia_m": 100,
        "duracion_s": 21,
    }
    assert geojson_tramos([]) == b""


# --- ClienteOsrm ----------------------------------------------------------------------------


def _cliente(manejador: Any) -> ClienteOsrm:
    return ClienteOsrm(
        "http://osrm:5000/", http=httpx.AsyncClient(transport=httpx.MockTransport(manejador))
    )


async def test_cliente_envia_longitud_latitud_y_lee_la_matriz() -> None:
    pedidas: list[httpx.Request] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        pedidas.append(request)
        return httpx.Response(200, json={"code": "Ok", "durations": [[0, 5], [6, 0]]})

    matriz = await _cliente(manejador).duraciones([(8.968, -79.539), (8.98, -79.52)])

    assert matriz == [[0, 5], [6, 0]]
    assert pedidas[0].url.path == "/table/v1/driving/-79.539000,8.968000;-79.520000,8.980000"


async def test_cliente_pide_la_ruta_con_geometria_por_pasos() -> None:
    pedidas: list[httpx.Request] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        pedidas.append(request)
        return httpx.Response(200, json={"code": "Ok", "routes": [], "waypoints": []})

    await _cliente(manejador).ruta([(8.968, -79.539), (8.98, -79.52)])

    params = dict(pedidas[0].url.params)
    assert params == {"overview": "false", "steps": "true", "geometries": "geojson"}


@pytest.mark.parametrize(
    ("respuesta", "error"),
    [
        (httpx.Response(400, json={"code": "NoRoute"}), SinRutaVialError),
        (httpx.Response(400, json={"code": "NoSegment"}), SinRutaVialError),
        (httpx.Response(400, json={"code": "TooBig"}), OsrmError),
        (httpx.Response(502, text="Bad Gateway"), OsrmError),
    ],
)
async def test_cliente_traduce_errores(respuesta: httpx.Response, error: type[Exception]) -> None:
    with pytest.raises(error):
        await _cliente(lambda request: respuesta).duraciones([(8.9, -79.5), (8.91, -79.5)])


async def test_cliente_sin_conexion_lanza_osrm_error() -> None:
    def manejador(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with pytest.raises(OsrmError):
        await _cliente(manejador).duraciones([(8.9, -79.5), (8.91, -79.5)])


# --- Contra un OSRM real (opcional) ---------------------------------------------------------


@pytest.mark.skipif(not os.getenv("OSRM_TEST_URL"), reason="OSRM_TEST_URL no definido")
async def test_osrm_real_ruta_por_calles_de_panama() -> None:
    osrm = ClienteOsrm(os.environ["OSRM_TEST_URL"])
    try:
        inspecciones = [_inspeccion(8.9839, -79.5245), _inspeccion(8.9935, -79.5237)]
        (ruta,) = await calcular_rutas(inspecciones, ORIGEN, osrm)
    finally:
        await osrm.cerrar()

    assert ruta.estado == "ok", ruta.motivo
    assert len(ruta.paradas) == 2 and len(ruta.tramos) == 2
    assert all(len(t.coordenadas) > 2 for t in ruta.tramos)  # sigue las calles, no una recta
