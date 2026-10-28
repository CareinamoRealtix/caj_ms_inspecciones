from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from app.application.subida_service import (
    EstadoSubida,
    SubidaCargaIncompletaError,
    SubidaCreada,
    SubidaFueraDeLimiteError,
    SubidaNoEncontradaError,
)
from app.infrastructure.clients.aws_sincronizacion import (
    EncolarJobError,
    SincronizacionNoDisponibleError,
)
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    get_current_user_email,
    get_subida_service,
)

SHA = "b" * 64
BODY = {"tamano_bytes": 100, "sha256": SHA, "cantidad_levantamientos": 2}


class FakeService:
    def __init__(self, *, error=None, estado=None) -> None:  # type: ignore[no-untyped-def]
        self.error = error
        self.estado = estado
        self.args: tuple = ()

    def _falla(self) -> None:
        if self.error:
            raise self.error

    async def iniciar(self, email, tamano, sha256, cantidad):  # type: ignore[no-untyped-def]
        self._falla()
        self.args = (email, tamano, sha256, cantidad)
        return SubidaCreada(
            "sub-1", "https://s3.test/zip?firmado", datetime(2026, 1, 1, tzinfo=UTC)
        )

    async def confirmar(self, subida_id, email):  # type: ignore[no-untyped-def]
        self._falla()
        return EstadoSubida(subida_id, "pendiente")

    async def consultar(self, subida_id, email, espera):  # type: ignore[no-untyped-def]
        self._falla()
        self.args = (subida_id, email, espera)
        return self.estado


async def _llamar(metodo: str, url: str, svc: FakeService, json=None):  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_subida_service] = lambda: svc
    app.dependency_overrides[get_current_user_email] = lambda: "insp@example.com"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.request(metodo, url, json=json)
    finally:
        app.dependency_overrides.clear()


async def test_crear_devuelve_201_con_url_de_carga() -> None:
    svc = FakeService()
    r = await _llamar("POST", "/v1/inspeccion/subidas", svc, BODY)
    assert r.status_code == 201
    assert r.json()["subida_id"] == "sub-1"
    assert r.json()["url_carga"].startswith("https://s3.test/")
    assert svc.args == ("insp@example.com", 100, SHA, 2)


async def test_crear_valida_el_body() -> None:
    r = await _llamar("POST", "/v1/inspeccion/subidas", FakeService(), {**BODY, "sha256": "xx"})
    assert r.status_code == 422


async def test_crear_zip_demasiado_grande_responde_413() -> None:
    r = await _llamar(
        "POST",
        "/v1/inspeccion/subidas",
        FakeService(error=SubidaFueraDeLimiteError("grande")),
        BODY,
    )
    assert r.status_code == 413


async def test_crear_deshabilitado_responde_503() -> None:
    r = await _llamar(
        "POST",
        "/v1/inspeccion/subidas",
        FakeService(error=SincronizacionNoDisponibleError()),
        BODY,
    )
    assert r.status_code == 503


async def test_confirmar_responde_202() -> None:
    r = await _llamar("POST", "/v1/inspeccion/subidas/sub-1/confirmar", FakeService())
    assert r.status_code == 202
    assert r.json()["estado"] == "pendiente"


async def test_confirmar_errores() -> None:
    for error, codigo in [
        (SubidaNoEncontradaError(), 404),
        (SubidaCargaIncompletaError(), 409),
        (EncolarJobError(), 502),
        (SincronizacionNoDisponibleError(), 503),
    ]:
        r = await _llamar(
            "POST", "/v1/inspeccion/subidas/sub-1/confirmar", FakeService(error=error)
        )
        assert r.status_code == codigo


async def test_get_devuelve_resultados_por_inspeccion() -> None:
    estado = EstadoSubida(
        "sub-1",
        "parcial",
        [
            {"id_inspeccion": "a", "exito": True, "id_levantamiento": "l1"},
            {"id_inspeccion": "b", "exito": False, "codigo_error": "archivo_faltante"},
        ],
    )
    svc = FakeService(estado=estado)
    r = await _llamar("GET", "/v1/inspeccion/subidas/sub-1?espera=7", svc)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "parcial"
    assert [x["exito"] for x in cuerpo["resultados"]] == [True, False]
    assert cuerpo["resultados"][1]["codigo_error"] == "archivo_faltante"
    assert svc.args == ("sub-1", "insp@example.com", 7)


async def test_get_ajena_responde_404() -> None:
    r = await _llamar(
        "GET", "/v1/inspeccion/subidas/x", FakeService(error=SubidaNoEncontradaError())
    )
    assert r.status_code == 404
