from httpx import ASGITransport, AsyncClient

from app.application.sincronizacion_service import EstadoJob, JobNoEncontradoError
from app.infrastructure.clients.aws_sincronizacion import (
    EncolarJobError,
    SincronizacionNoDisponibleError,
)
from app.infrastructure.config.settings import Settings, get_settings
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    get_current_user_email,
    get_sincronizacion_service,
)


class FakeService:
    def __init__(self, *, iniciar_error=None, consultar_error=None, estado=None) -> None:  # type: ignore[no-untyped-def]
        self.iniciar_error = iniciar_error
        self.consultar_error = consultar_error
        self.estado = estado
        self.args: tuple = ()

    async def iniciar(self, email: str, origen: tuple[float, float] | None = None) -> str:
        if self.iniciar_error:
            raise self.iniciar_error
        self.args = (email, origen)
        return "job-123"

    async def consultar(self, job_id: str, email: str, espera: int) -> EstadoJob:
        if self.consultar_error:
            raise self.consultar_error
        self.args = (job_id, email, espera)
        return self.estado


async def _llamar(metodo: str, url: str, svc: FakeService, json=None):  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_sincronizacion_service] = lambda: svc
    app.dependency_overrides[get_current_user_email] = lambda: "insp@example.com"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.request(metodo, url, json=json)
    finally:
        app.dependency_overrides.clear()


async def test_post_devuelve_202_con_job_id() -> None:
    svc = FakeService()
    r = await _llamar("POST", "/v1/inspeccion/sincronizacion", svc)
    assert r.status_code == 202
    assert r.json() == {"job_id": "job-123", "estado": "pendiente"}
    assert svc.args == ("insp@example.com", None)


async def test_post_con_origen_lo_pasa_al_servicio() -> None:
    svc = FakeService()
    cuerpo = {"origen": {"latitud": 8.98, "longitud": -79.53, "precision_m": 15}}
    r = await _llamar("POST", "/v1/inspeccion/sincronizacion", svc, json=cuerpo)
    assert r.status_code == 202
    assert svc.args == ("insp@example.com", (8.98, -79.53))


async def test_post_con_body_sin_origen_equivale_a_sin_body() -> None:
    svc = FakeService()
    r = await _llamar("POST", "/v1/inspeccion/sincronizacion", svc, json={})
    assert r.status_code == 202
    assert svc.args == ("insp@example.com", None)


async def test_post_con_origen_invalido_responde_422() -> None:
    cuerpo = {"origen": {"latitud": 91, "longitud": -79.53}}
    r = await _llamar("POST", "/v1/inspeccion/sincronizacion", FakeService(), json=cuerpo)
    assert r.status_code == 422


async def test_post_deshabilitado_responde_503() -> None:
    r = await _llamar(
        "POST",
        "/v1/inspeccion/sincronizacion",
        FakeService(iniciar_error=SincronizacionNoDisponibleError()),
    )
    assert r.status_code == 503


async def test_post_falla_encolado_responde_502() -> None:
    r = await _llamar(
        "POST", "/v1/inspeccion/sincronizacion", FakeService(iniciar_error=EncolarJobError())
    )
    assert r.status_code == 502


async def test_get_listo_incluye_url_firmada() -> None:
    svc = FakeService(estado=EstadoJob("job-123", "listo", url_firmada="https://cdn/x?s"))
    r = await _llamar("GET", "/v1/inspeccion/sincronizacion/job-123?espera=3", svc)
    assert r.status_code == 200
    assert r.json() == {
        "job_id": "job-123",
        "estado": "listo",
        "url_firmada": "https://cdn/x?s",
        "error": None,
    }
    assert svc.args == ("job-123", "insp@example.com", 3)


async def test_get_job_ajeno_o_inexistente_responde_404() -> None:
    r = await _llamar(
        "GET",
        "/v1/inspeccion/sincronizacion/zzz",
        FakeService(consultar_error=JobNoEncontradoError("zzz")),
    )
    assert r.status_code == 404


async def test_get_deshabilitado_responde_503() -> None:
    r = await _llamar(
        "GET",
        "/v1/inspeccion/sincronizacion/zzz",
        FakeService(consultar_error=SincronizacionNoDisponibleError()),
    )
    assert r.status_code == 503


async def test_post_sin_cabecera_de_usuario_responde_401() -> None:
    app.dependency_overrides[get_sincronizacion_service] = lambda: FakeService()
    app.dependency_overrides[get_settings] = lambda: Settings(is_local=False, _env_file=None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/inspeccion/sincronizacion")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 401
