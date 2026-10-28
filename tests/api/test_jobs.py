from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.alertas_vencimiento_service import AlertasVencimientoResultado
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    get_alertas_vencimiento_service,
    get_current_user_email,
)


class FakeAlertasVencimientoService:
    def __init__(self) -> None:
        self.emitir_args: dict[str, Any] | None = None

    async def emitir(self, *, creado_por: str | None) -> AlertasVencimientoResultado:
        self.emitir_args = {"creado_por": creado_por}
        return AlertasVencimientoResultado(
            fincas_evaluadas=5,
            notificaciones_creadas=3,
            notificaciones_silenciadas=1,
            fincas_omitidas_sin_inspector=2,
        )


async def test_post_alertas_vencimiento_returns_summary_and_forwards_user() -> None:
    service = FakeAlertasVencimientoService()
    app.dependency_overrides[get_alertas_vencimiento_service] = lambda: service
    app.dependency_overrides[get_current_user_email] = lambda: "oficial@example.com"

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/inspeccion/jobs/alertas-vencimiento")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "fincas_evaluadas": 5,
        "notificaciones_creadas": 3,
        "notificaciones_silenciadas": 1,
        "fincas_omitidas_sin_inspector": 2,
    }
    assert service.emitir_args == {"creado_por": "oficial@example.com"}
