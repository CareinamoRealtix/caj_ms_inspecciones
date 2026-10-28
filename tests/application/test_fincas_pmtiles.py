import json
import shutil
import subprocess
import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.application.fincas_pmtiles import (
    PmtilesError,
    construir_geojson,
    generar_capa_fincas,
    generar_pmtiles,
)


def _inspeccion(
    lat: float | None,
    lng: float | None,
    finca: str = "101010",
    fecha: date = date(2026, 10, 16),
) -> Any:
    return SimpleNamespace(
        id_inspeccion=uuid.UUID("b1f10411-d4bf-47ee-8b09-519f04794f55"),
        numero_inspeccion=175,
        fecha_programada=fecha,
        finca=SimpleNamespace(latitud=lat, longitud=lng, numero_finca=finca),
    )


def test_geojson_un_punto_por_inspeccion_en_orden_lng_lat() -> None:
    r = construir_geojson([_inspeccion(8.98, -79.52), _inspeccion(9.04, -79.49, "202020")])

    assert (r.total, r.sin_coordenadas, r.fuera_de_panama) == (2, 0, 0)
    features = [json.loads(linea) for linea in r.contenido.decode().splitlines()]
    assert features[0]["geometry"] == {"type": "Point", "coordinates": [-79.52, 8.98]}
    assert features[0]["properties"] == {
        "id_inspeccion": "b1f10411-d4bf-47ee-8b09-519f04794f55",
        "numero_inspeccion": 175,
        "numero_finca": "101010",
        "fecha_programada": "2026-10-16",
        "estado": "Activa",
        "asignada_al_usuario": True,
    }
    assert features[1]["properties"]["numero_finca"] == "202020"


@pytest.mark.parametrize(
    ("lat", "lng"),
    [(None, None), (8.9, None), (None, -79.5), (0, 0), (91, -79.5), (8.9, 181), (float("nan"), 1)],
)
def test_geojson_descarta_coordenadas_invalidas(lat: float | None, lng: float | None) -> None:
    r = construir_geojson([_inspeccion(lat, lng)])

    assert (r.total, r.sin_coordenadas) == (0, 1)
    assert r.contenido == b""


@pytest.mark.parametrize(("lat", "lng"), [(3.2343, -79.9), (9.0, -75.0), (8.98, 79.52)])
def test_geojson_descarta_puntos_fuera_de_panama(lat: float, lng: float) -> None:
    r = construir_geojson([_inspeccion(lat, lng)])

    assert (r.total, r.fuera_de_panama, r.sin_coordenadas) == (0, 1, 0)


def test_geojson_cuenta_puntos_por_fecha_ordenados_y_solo_los_incluidos() -> None:
    hoy, manana = date(2026, 10, 17), date(2026, 10, 18)

    r = construir_geojson(
        [
            _inspeccion(8.98, -79.52, fecha=manana),
            _inspeccion(9.04, -79.49, fecha=hoy),
            _inspeccion(8.99, -79.50, fecha=manana),
            _inspeccion(None, None, fecha=hoy),  # sin coordenadas: no cuenta
            _inspeccion(3.23, -79.90, fecha=date(2026, 10, 19)),  # fuera de Panamá: no cuenta
        ]
    )

    assert r.por_fecha == {hoy: 1, manana: 2}
    assert list(r.por_fecha) == [hoy, manana]
    assert sum(r.por_fecha.values()) == r.total


class _Ejecutor:
    def __init__(self, returncode: int = 0, escribe: bool = True, error: Exception | None = None):
        self.returncode, self.escribe, self.error = returncode, escribe, error
        self.comando: list[str] = []

    def __call__(self, comando: list[str], **kwargs: Any) -> Any:
        self.comando = comando
        if self.error:
            raise self.error
        if self.escribe:
            with open(comando[comando.index("-o") + 1], "wb") as f:
                f.write(b"PMTiles-falso")
        return SimpleNamespace(returncode=self.returncode, stderr=b"boom")


def test_generar_pmtiles_arma_el_comando_y_devuelve_el_archivo() -> None:
    ejecutor = _Ejecutor()

    contenido = generar_pmtiles(b'{"a":1}\n', binario="tc", ejecutar=ejecutor)

    assert contenido == b"PMTiles-falso"
    c = ejecutor.comando
    assert c[0] == "tc"
    capas = [c[i + 1].split(":")[0] for i, arg in enumerate(c) if arg == "-L"]
    assert capas == ["fincas"]
    assert (c[c.index("-Z") + 1], c[c.index("-z") + 1]) == ("5", "15")
    assert {"-r1", "--no-feature-limit", "--no-tile-size-limit"} <= set(c)


def test_generar_pmtiles_con_rutas_agrega_la_capa_rutas() -> None:
    ejecutor = _Ejecutor()

    generar_pmtiles(b'{"a":1}\n', b'{"b":2}\n', binario="tc", ejecutar=ejecutor)

    c = ejecutor.comando
    capas = [c[i + 1].split(":")[0] for i, arg in enumerate(c) if arg == "-L"]
    assert capas == ["fincas", "rutas"]


def test_geojson_agrega_orden_ruta_solo_a_las_inspecciones_con_parada() -> None:
    con_ruta = _inspeccion(8.98, -79.52)
    sin_ruta = SimpleNamespace(**{**vars(_inspeccion(9.04, -79.49)), "id_inspeccion": uuid.uuid4()})

    r = construir_geojson([con_ruta, sin_ruta], {con_ruta.id_inspeccion: 3})

    props = [json.loads(linea)["properties"] for linea in r.contenido.decode().splitlines()]
    assert props[0]["orden_ruta"] == 3
    assert "orden_ruta" not in props[1]


@pytest.mark.parametrize(
    "ejecutor",
    [
        _Ejecutor(returncode=1),
        _Ejecutor(escribe=False),
        _Ejecutor(error=FileNotFoundError()),
        _Ejecutor(error=subprocess.TimeoutExpired("tc", 1)),
    ],
)
def test_generar_pmtiles_falla_con_pmtiles_error(ejecutor: _Ejecutor) -> None:
    with pytest.raises(PmtilesError):
        generar_pmtiles(b"x\n", ejecutar=ejecutor)


async def test_capa_fincas_devuelve_el_pmtiles_y_el_total() -> None:
    recibido: list[bytes] = []

    def generador(geojson: bytes, rutas: bytes | None) -> bytes:
        recibido.append(geojson)
        assert rutas is None
        return b"PM"

    capa = await generar_capa_fincas(
        [_inspeccion(8.98, -79.52), _inspeccion(None, None)], generador=generador
    )

    assert capa is not None and (capa.pmtiles, capa.total_puntos) == (b"PM", 1)
    assert capa.por_fecha == {date(2026, 10, 16): 1}
    assert capa.con_rutas is False
    assert recibido[0].count(b"\n") == 1


async def test_capa_fincas_con_rutas_las_pasa_al_generador() -> None:
    recibido: list[bytes | None] = []

    def generador(geojson: bytes, rutas: bytes | None) -> bytes:
        recibido.append(rutas)
        return b"PM"

    capa = await generar_capa_fincas(
        [_inspeccion(8.98, -79.52)], generador=generador, rutas_geojson=b"linea\n"
    )

    assert capa is not None and capa.con_rutas is True
    assert recibido == [b"linea\n"]


async def test_capa_fincas_sin_puntos_no_invoca_tippecanoe() -> None:
    def generador(geojson: bytes, rutas: bytes | None) -> bytes:
        raise AssertionError("no debía llamarse")

    assert await generar_capa_fincas([_inspeccion(None, None)], generador=generador) is None
    assert await generar_capa_fincas([], generador=generador) is None


async def test_capa_fincas_ante_falla_devuelve_none_sin_lanzar() -> None:
    def generador(geojson: bytes, rutas: bytes | None) -> bytes:
        raise PmtilesError("boom")

    assert await generar_capa_fincas([_inspeccion(8.98, -79.52)], generador=generador) is None


@pytest.mark.skipif(shutil.which("tippecanoe") is None, reason="tippecanoe no está instalado")
def test_generar_pmtiles_real_produce_un_pmtiles_v3_vectorial() -> None:
    geojson = construir_geojson([_inspeccion(8.98, -79.52), _inspeccion(9.04, -79.49)]).contenido

    contenido = generar_pmtiles(geojson)

    assert contenido[:7] == b"PMTiles" and contenido[7] == 3  # cabecera v3
    assert contenido[99] == 1  # tile_type = MVT (vectorial)
    assert (contenido[100], contenido[101]) == (5, 15)  # zoom mínimo y máximo
