from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.inspeccion_service import InspeccionService
from app.infrastructure.clients.azure_ad_client import AzureAdError
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    get_azure_ad_client,
    get_inspeccion_service,
)

_INSPECCION_ID = "00000000-0000-4000-8000-000000000601"


class FakeAzureAdClient:
    def __init__(
        self, members: list[dict[str, Any]] | None = None, *, fails: bool = False
    ) -> None:
        self.members = members or []
        self.fails = fails
        self.closed = False

    async def get_inspectores(self) -> list[dict[str, Any]]:
        if self.fails:
            raise AzureAdError(status_code=502, detail="No se pudo consultar Microsoft Graph.")
        return self.members

    async def aclose(self) -> None:
        self.closed = True


class DetalleRepository:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def get_detalle(self, id_inspeccion: uuid.UUID) -> dict[str, Any] | None:
        return self._row

    async def get_fotografias_by_inspeccion(self, id_inspeccion: uuid.UUID) -> list[Any]:
        return []

    async def get_levantamiento_opciones_activas(self) -> list[dict[str, Any]]:
        return [
            {
                "tipo_catalogo": "CONDICION_BIEN",
                "codigo": "BUENA",
                "nombre": "Buena",
                "requiere_cantidad": False,
                "permite_descripcion": False,
                "orden": 1,
            }
        ]


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id_inspeccion": uuid.UUID(_INSPECCION_ID),
        "numero_inspeccion": 1,
        "numero_finca": "304826291",
        "id_bien_inventario": uuid.uuid4(),
        "ruta_id": uuid.uuid4(),
        "ruta_nombre": "Ruta 1",
        "fecha_programada": date(2026, 8, 2),
        "fecha_realizada": date(2026, 8, 2),
        "tipo_inspeccion": "Inspección de Rutina",
        "descripcion_tipo": None,
        "email_inspector": "francisco.delarosa@example.com",
        "estado_inspeccion": "Finalizada",
        "color_badge": "#007bff",
        "origen": "programada",
        "provincia": "Panamá",
        "distrito": "Panamá",
        "corregimiento": "Pacora",
        "barriada_sector": "Residencial Mirador del Bosque",
        "direccion": "Calle Principal",
        "numero_lote": "Casa 215",
        "id_levantamiento": None,
        "coordenadas": None,
        "condicion_bien": None,
        "estado_ocupacion": None,
        "nombre_ocupante": None,
        "tipo_identificacion_ocup": None,
        "numero_identificacion_ocup": None,
        "numero_contacto_ocupante": None,
        "comentarios_ocupante": None,
        "puertas": None,
        "tipos_ventanas": None,
        "servicios_publicos": None,
        "distribucion_inmueble": None,
        "servicios_requeridos": None,
        "inspeccion_tecnica_req": False,
        "tipos_inspeccion_tecnica": None,
        "motivacion": None,
        "url_firma_inspector": None,
        "observaciones": None,
        "fecha_levantamiento": None,
    }
    base.update(overrides)
    return base


async def test_get_pdf_retorna_documento_pdf_valido() -> None:
    service = InspeccionService(repo=DetalleRepository(_row()))  # type: ignore[arg-type]
    fake_azure = FakeAzureAdClient(
        [{"displayName": "Francisco De La Rosa", "mail": "francisco.delarosa@example.com"}]
    )
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    app.dependency_overrides[get_azure_ad_client] = lambda: fake_azure
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/v1/inspeccion/{_INSPECCION_ID}/pdf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "inspeccion_1.pdf" in response.headers["content-disposition"]
    assert fake_azure.closed is True


async def test_get_pdf_usa_correo_si_falla_la_resolucion_de_azure() -> None:
    service = InspeccionService(repo=DetalleRepository(_row()))  # type: ignore[arg-type]
    fake_azure = FakeAzureAdClient(fails=True)
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    app.dependency_overrides[get_azure_ad_client] = lambda: fake_azure
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/v1/inspeccion/{_INSPECCION_ID}/pdf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


async def test_get_pdf_responde_404_si_la_inspeccion_no_existe() -> None:
    service = InspeccionService(repo=DetalleRepository(None))  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    app.dependency_overrides[get_azure_ad_client] = lambda: FakeAzureAdClient()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/v1/inspeccion/{_INSPECCION_ID}/pdf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
