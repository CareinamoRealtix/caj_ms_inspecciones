import io
import itertools
import json
import uuid
import zipfile
from datetime import UTC, date, datetime
from types import SimpleNamespace

import boto3
import pytest
from fakes import FakeJobStore as JobStore
from fakes import reiniciar
from moto import mock_aws

from app.application.fincas_pmtiles import CapaFincas
from app.application.rutas_optimas import Origen
from app.infrastructure.clients.aws_sincronizacion import ZipUploader
from app.infrastructure.config.settings import Settings
from app.jobs.generar_sincronizacion import NOMBRE_JSON, clave_s3, construir_zip, generar, main

BUCKET = "bucket-test"


class FakeServicio:
    def __init__(self, falla: bool = False, inspecciones: list | None = None) -> None:  # type: ignore[type-arg]
        self.falla = falla
        self.inspecciones = inspecciones or []

    async def get_sincronizacion(self, email: str):  # type: ignore[no-untyped-def]
        if self.falla:
            raise RuntimeError("db caída")
        meta = SimpleNamespace(mapa=None)
        respuesta = SimpleNamespace(meta=meta, inspecciones=self.inspecciones, rutas_optimas=[])
        respuesta.model_dump_json = lambda: json.dumps(
            {
                "meta": {"email": email, "mapa": meta.mapa and meta.mapa.model_dump(mode="json")},
                **(
                    {"rutas_optimas": [r.model_dump(mode="json") for r in respuesta.rutas_optimas]}
                    if respuesta.rutas_optimas
                    else {}
                ),
            }
        )
        return respuesta


@pytest.fixture
def aws():  # type: ignore[no-untyped-def]
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        reiniciar()
        settings = Settings(sincronizacion_s3_bucket=BUCKET, _env_file=None)
        yield settings, None


def test_construir_zip_deja_el_json_en_la_raiz() -> None:
    contenido = construir_zip(b'{"a": 1}')
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        assert z.namelist() == [NOMBRE_JSON]
        assert z.read(NOMBRE_JSON) == b'{"a": 1}'


def test_clave_s3_no_incluye_el_email() -> None:
    clave = clave_s3("abc", datetime(2026, 10, 7, tzinfo=UTC))
    assert clave == "sincronizacion/2026-10-07/abc.zip"


async def test_generar_sube_el_zip_y_marca_listo(aws) -> None:  # type: ignore[no-untyped-def]
    settings, _ = aws
    store = JobStore(settings)
    await store.crear("j1", "insp@example.com")

    s3_key = await generar(
        "j1",
        "insp@example.com",
        servicio=FakeServicio(),  # type: ignore[arg-type]
        store=store,
        uploader=ZipUploader(settings),
    )

    job = await store.obtener("j1")
    assert job is not None and job.estado == "listo" and job.s3_key == s3_key
    cuerpo = (
        boto3.client("s3", region_name="us-east-1")
        .get_object(Bucket=BUCKET, Key=s3_key)["Body"]
        .read()
    )
    with zipfile.ZipFile(io.BytesIO(cuerpo)) as z:
        assert z.namelist() == [NOMBRE_JSON]
        assert json.loads(z.read(NOMBRE_JSON)) == {
            "meta": {"email": "insp@example.com", "mapa": None}
        }


async def test_generar_ante_error_marca_error_sin_filtrar_detalle(aws) -> None:  # type: ignore[no-untyped-def]
    settings, _ = aws
    store = JobStore(settings)
    await store.crear("j2", "insp@example.com")

    with pytest.raises(RuntimeError):
        await generar(
            "j2",
            "insp@example.com",
            servicio=FakeServicio(falla=True),  # type: ignore[arg-type]
            store=store,
            uploader=ZipUploader(settings),
        )

    job = await store.obtener("j2")
    assert job is not None and job.estado == "error"
    assert "db caída" not in (job.error or "")


def test_construir_zip_con_pmtiles_lo_guarda_sin_recomprimir() -> None:
    contenido = construir_zip(b"{}", b"PMTiles-binario")
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        assert z.namelist() == [NOMBRE_JSON, "fincas.pmtiles"]
        assert z.read("fincas.pmtiles") == b"PMTiles-binario"
        assert z.getinfo("fincas.pmtiles").compress_type == zipfile.ZIP_STORED


def _leer_zip(settings: Settings, s3_key: str) -> zipfile.ZipFile:
    cuerpo = (
        boto3.client("s3", region_name="us-east-1")
        .get_object(Bucket=settings.sincronizacion_s3_bucket, Key=s3_key)["Body"]
        .read()
    )
    return zipfile.ZipFile(io.BytesIO(cuerpo))


async def test_generar_agrega_fincas_pmtiles_y_meta_mapa(aws, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings, _ = aws
    store = JobStore(settings)
    await store.crear("j3", "insp@example.com")
    # Desordenado a propósito: meta.mapa.fechas debe salir ascendente.
    capa = CapaFincas(b"PMTILES", 3, {date(2026, 10, 18): 2, date(2026, 10, 17): 1})

    async def falsa_capa(inspecciones, *, generador, **_):  # type: ignore[no-untyped-def]
        assert generador is not None
        return capa

    monkeypatch.setattr("app.jobs.generar_sincronizacion.generar_capa_fincas", falsa_capa)

    s3_key = await generar(
        "j3",
        "insp@example.com",
        servicio=FakeServicio(),  # type: ignore[arg-type]
        store=store,
        uploader=ZipUploader(settings),
        generador_pmtiles=lambda geojson: b"",
    )

    with _leer_zip(settings, s3_key) as z:
        assert z.read("fincas.pmtiles") == b"PMTILES"
        mapa = json.loads(z.read(NOMBRE_JSON))["meta"]["mapa"]
    assert mapa == {
        "fincas_pmtiles": "fincas.pmtiles",
        "capa": "fincas",
        "total_puntos": 3,
        "fechas": [
            {"fecha": "2026-10-17", "total_puntos": 1},
            {"fecha": "2026-10-18", "total_puntos": 2},
        ],
        "capa_rutas": None,
    }


async def test_generar_sin_capa_sube_el_zip_sin_pmtiles(aws, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings, _ = aws
    store = JobStore(settings)
    await store.crear("j4", "insp@example.com")

    async def sin_capa(inspecciones, *, generador, **_):  # type: ignore[no-untyped-def]
        return None  # sin puntos, o tippecanoe falló

    monkeypatch.setattr("app.jobs.generar_sincronizacion.generar_capa_fincas", sin_capa)

    s3_key = await generar(
        "j4",
        "insp@example.com",
        servicio=FakeServicio(),  # type: ignore[arg-type]
        store=store,
        uploader=ZipUploader(settings),
        generador_pmtiles=lambda geojson: b"",
    )

    job = await store.obtener("j4")
    assert job is not None and job.estado == "listo"
    with _leer_zip(settings, s3_key) as z:
        assert z.namelist() == [NOMBRE_JSON]
        assert json.loads(z.read(NOMBRE_JSON))["meta"]["mapa"] is None


async def test_generar_con_pmtiles_deshabilitado_no_intenta_generarlo(aws, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings, _ = aws
    store = JobStore(settings)
    await store.crear("j5", "insp@example.com")

    async def no_debe_llamarse(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("generar_capa_fincas no debía llamarse")

    monkeypatch.setattr("app.jobs.generar_sincronizacion.generar_capa_fincas", no_debe_llamarse)

    s3_key = await generar(
        "j5",
        "insp@example.com",
        servicio=FakeServicio(),  # type: ignore[arg-type]
        store=store,
        uploader=ZipUploader(settings),
    )

    with _leer_zip(settings, s3_key) as z:
        assert z.namelist() == [NOMBRE_JSON]


class _OsrmRecto:
    """OSRM falso: duración proporcional a la distancia; la ruta es la recta entre puntos."""

    async def duraciones(self, puntos):  # type: ignore[no-untyped-def]
        return [[abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in puntos] for a in puntos]

    async def ruta(self, puntos):  # type: ignore[no-untyped-def]
        legs = [
            {
                "distance": 500,
                "duration": 60,
                "steps": [{"geometry": {"coordinates": [[a[1], a[0]], [b[1], b[0]]]}}],
            }
            for a, b in itertools.pairwise(puntos)
        ]
        return {
            "routes": [{"distance": 500 * len(legs), "duration": 60 * len(legs), "legs": legs}],
            "waypoints": [{"distance": 3} for _ in puntos],
        }


def _inspeccion_job(numero: int, lat: float, lng: float):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id_inspeccion=uuid.UUID(int=numero),
        numero_inspeccion=numero,
        fecha_programada=date(2026, 11, 17),
        finca=SimpleNamespace(latitud=lat, longitud=lng, numero_finca=str(numero)),
    )


async def test_generar_con_origen_agrega_rutas_y_capa_rutas(aws) -> None:  # type: ignore[no-untyped-def]
    settings, _ = aws
    store = JobStore(settings)
    await store.crear("j5", "insp@example.com")
    lejos, cerca = _inspeccion_job(2, 8.99, -79.53), _inspeccion_job(1, 8.97, -79.53)
    recibido: dict[str, bytes | None] = {}

    def generador(fincas: bytes, rutas: bytes | None) -> bytes:
        recibido["fincas"], recibido["rutas"] = fincas, rutas
        return b"PMTILES"

    s3_key = await generar(
        "j5",
        "insp@example.com",
        servicio=FakeServicio(inspecciones=[lejos, cerca]),  # type: ignore[arg-type]
        store=store,
        uploader=ZipUploader(settings),
        generador_pmtiles=generador,
        origen=Origen(8.96, -79.53),
        osrm=_OsrmRecto(),
    )

    with _leer_zip(settings, s3_key) as z:
        cuerpo = json.loads(z.read(NOMBRE_JSON))
    assert cuerpo["meta"]["mapa"]["capa_rutas"] == "rutas"
    (ruta,) = cuerpo["rutas_optimas"]
    assert (ruta["fecha"], ruta["estado"], ruta["distancia_m"]) == ("2026-11-17", "ok", 1000)
    assert ruta["origen"] == {"latitud": 8.96, "longitud": -79.53}
    assert [p["id_inspecciones"] for p in ruta["paradas"]] == [
        [str(cerca.id_inspeccion)],
        [str(lejos.id_inspeccion)],
    ]
    # Puntos con su número de parada y una línea por tramo en la capa `rutas`.
    puntos = [json.loads(linea)["properties"] for linea in recibido["fincas"].decode().splitlines()]  # type: ignore[union-attr]
    assert {p["numero_finca"]: p["orden_ruta"] for p in puntos} == {"1": 1, "2": 2}
    assert recibido["rutas"] is not None and recibido["rutas"].count(b"LineString") == 2


async def test_generar_sin_origen_no_calcula_rutas(aws) -> None:  # type: ignore[no-untyped-def]
    settings, _ = aws
    store = JobStore(settings)
    await store.crear("j6", "insp@example.com")
    recibido: list[bytes | None] = []

    def generador(fincas: bytes, rutas: bytes | None) -> bytes:
        recibido.append(rutas)
        return b"PMTILES"

    s3_key = await generar(
        "j6",
        "insp@example.com",
        servicio=FakeServicio(inspecciones=[_inspeccion_job(1, 8.97, -79.53)]),  # type: ignore[arg-type]
        store=store,
        uploader=ZipUploader(settings),
        generador_pmtiles=generador,
        osrm=_OsrmRecto(),
    )

    with _leer_zip(settings, s3_key) as z:
        cuerpo = json.loads(z.read(NOMBRE_JSON))
    assert "rutas_optimas" not in cuerpo  # el fake solo la serializa si no está vacía
    assert cuerpo["meta"]["mapa"]["capa_rutas"] is None
    assert recibido == [None]


def test_main_exige_origen_completo() -> None:
    with pytest.raises(SystemExit):
        main(["--job-id", "x", "--email", "a@b.c", "--origen-lat", "8.9"])
