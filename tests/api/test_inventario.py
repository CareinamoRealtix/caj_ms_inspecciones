from typing import Any

from httpx import ASGITransport, AsyncClient, Response

from app.application.inspeccion_service import InspeccionService
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    get_azure_ad_client,
    get_inspeccion_service,
)


class FakeAzureAdClient:
    async def get_inspectores(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "user-1",
                "displayName": "Inspector 1",
                "userPrincipalName": "inspector@example.com",
                "mail": None,
            }
        ]

    async def aclose(self) -> None:
        pass


class EmptyInventoryRepository:
    async def get_inventario(self, **kwargs: Any) -> tuple[list[Any], int]:
        return [], 0

    async def get_historico_by_finca(
        self, numero_finca: str | None, pagina: int, tamanio: int, **kwargs: Any
    ) -> tuple[list[Any], int]:
        return [], 0

    async def get_catalogos_gestion(self) -> list[dict[str, Any]]:
        return [
            {
                "tipo_catalogo": "ESTADO_OCUPACION",
                "id": 1,
                "id_padre": None,
                "nombre": "Ocupado",
            },
            {
                "tipo_catalogo": "ESTADO_OCUPACION",
                "id": 6,
                "id_padre": None,
                "nombre": "Vendido",
            },
            {
                "tipo_catalogo": "PROVINCIA",
                "id": 8,
                "id_padre": None,
                "nombre": "Panamá",
            },
            {
                "tipo_catalogo": "DISTRITO",
                "id": 1,
                "id_padre": 8,
                "nombre": "Panamá",
            },
            {
                "tipo_catalogo": "CORREGIMIENTO",
                "id": 4,
                "id_padre": 1,
                "nombre": "Bella Vista",
            },
        ]

    async def get_rutas(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "00000000-0000-4000-8000-000000000101",
                "codigo": "RUTA-001",
                "nombre": "Ruta Centro",
            }
        ]


async def _request(path: str) -> Response:
    service = InspeccionService(repo=EmptyInventoryRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    app.dependency_overrides[get_azure_ad_client] = FakeAzureAdClient
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


async def test_management_catalogs_endpoint_returns_filter_options() -> None:
    response = await _request("/v1/inspeccion/gestion/catalogos")

    assert response.status_code == 200
    payload = response.json()
    assert payload["alertas"] == ["TERMINO", "VENCIDA", "PROXIMA"]
    assert payload["estatus_bien_inventario"] == [{"id": 1, "estado": "Ocupado"}]
    assert all(item["id"] != 6 for item in payload["estatus_bien_inventario"])
    assert "estados" not in payload
    assert payload["provincias"] == [{"id": 8, "nombre": "Panamá"}]
    assert payload["distritos"] == [{"id": 1, "nombre": "Panamá", "id_provincia": 8}]
    assert payload["corregimientos"] == [{"id": 4, "nombre": "Bella Vista", "id_distrito": 1}]
    assert payload["inspectores"][0] == {
        "displayName": "Inspector 1",
        "mail": "inspector@example.com",
    }
    assert payload["rutas"][0] == {
        "id": "00000000-0000-4000-8000-000000000101",
        "codigo": "RUTA-001",
        "nombre": "Ruta Centro",
    }


async def test_management_endpoint_accepts_inventory_status_filter() -> None:
    response = await _request(
        "/v1/inspeccion/gestion?pagina=1&tamanio=15&numero_finca=5566&estatus_bien_inventario=4&provincia=8&distrito=1&corregimiento=4"
    )

    assert response.status_code == 200


async def test_control_endpoint_accepts_inventory_status_filter() -> None:
    response = await _request("/v1/inspeccion/control?estatus_bien_inventario=4")

    assert response.status_code == 200


async def test_control_endpoint_rejects_invalid_inventory_status() -> None:
    response = await _request("/v1/inspeccion/control?estatus_bien_inventario=0")

    assert response.status_code == 422


async def test_management_endpoint_accepts_new_entry_filter() -> None:
    response = await _request("/v1/inspeccion/gestion?nuevo_ingreso=true")

    assert response.status_code == 200


async def test_management_endpoint_accepts_alert_filter() -> None:
    response = await _request("/v1/inspeccion/gestion?alerta=PROXIMA")

    assert response.status_code == 200


async def test_control_endpoint_rejects_old_boolean_alert_filter() -> None:
    response = await _request("/v1/inspeccion/control?alerta=true")

    assert response.status_code == 422


async def test_management_endpoint_accepts_route_filter() -> None:
    response = await _request(
        "/v1/inspeccion/gestion?ruta=00000000-0000-4000-8000-000000000101"
    )

    assert response.status_code == 200


async def test_management_endpoint_accepts_inspector_filter() -> None:
    response = await _request(
        "/v1/inspeccion/gestion?inspector=6ae0b6ab-769d-4d14-9174-10e63173c65d"
    )

    assert response.status_code == 200


async def test_control_endpoint_exposes_only_its_supported_filters() -> None:
    response = await _request(
        "/v1/inspeccion/control?pagina=1&tamanio=15&inspector="
        "6ae0b6ab-769d-4d14-9174-10e63173c65d"
    )

    assert response.status_code == 200
    parameters = {
        parameter["name"]
        for parameter in app.openapi()["paths"]["/v1/inspeccion/control"]["get"]["parameters"]
    }
    assert parameters == {
        "pagina",
        "tamanio",
        "numero_finca",
        "estatus_bien_inventario",
        "provincia",
        "distrito",
        "corregimiento",
        "alerta",
        "inspector",
        "month_expiration",
        "fecha_desde",
        "fecha_hasta",
    }
    response_schema = app.openapi()["paths"]["/v1/inspeccion/control"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/ControlResponse"}
    status_schema = app.openapi()["components"]["schemas"]["ControlItemResponse"][
        "properties"
    ]["estado_inspeccion"]
    assert status_schema["anyOf"][0]["enum"] == ["VENCIDA", "PROXIMA", "TERMINO"]
    control_item_schema = app.openapi()["components"]["schemas"]["ControlItemResponse"]
    numero_inspeccion_schema = control_item_schema["properties"]["numero_inspeccion"]
    assert {"type": "string"} in numero_inspeccion_schema["anyOf"]
    assert "numero_inspeccion" not in control_item_schema.get("required", [])


async def test_history_endpoint_exposes_only_its_supported_filters() -> None:
    response = await _request(
        "/v1/inspeccion/historico?pagina=1&tamanio=15&numero_finca=3099"
        "&provincia=8&distrito=1&corregimiento=4"
    )

    assert response.status_code == 200
    parameters = {
        parameter["name"]
        for parameter in app.openapi()["paths"]["/v1/inspeccion/historico"]["get"]["parameters"]
    }
    assert parameters == {
        "numero_finca",
        "pagina",
        "tamanio",
        "provincia",
        "distrito",
        "corregimiento",
        "ruta",
        "inspector",
        "month_last_insp",
        "fecha_desde",
        "fecha_hasta",
    }
    history_item_schema = app.openapi()["components"]["schemas"][
        "HistoricoItemResponse"
    ]
    assert "id_inspeccion" in history_item_schema["properties"]
    assert "id_inspeccion" in history_item_schema["required"]


async def test_history_endpoint_accepts_request_without_numero_finca() -> None:
    response = await _request("/v1/inspeccion/historico?pagina=1&tamanio=15")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["total_registros"] == 0


async def test_history_endpoint_rejects_distrito_without_provincia() -> None:
    response = await _request(
        "/v1/inspeccion/historico?numero_finca=3099&distrito=1"
    )

    assert response.status_code == 422


async def test_history_endpoint_rejects_corregimiento_without_distrito() -> None:
    response = await _request(
        "/v1/inspeccion/historico?numero_finca=3099&provincia=8&corregimiento=4"
    )

    assert response.status_code == 422


async def test_management_endpoint_accepts_last_inspection_month_filter() -> None:
    response = await _request("/v1/inspeccion/gestion?month_last_insp=8")

    assert response.status_code == 200


async def test_management_endpoint_rejects_invalid_last_inspection_month() -> None:
    response = await _request("/v1/inspeccion/gestion?month_last_insp=13")

    assert response.status_code == 422


async def test_control_endpoint_accepts_expiration_month_filter() -> None:
    response = await _request("/v1/inspeccion/control?month_expiration=8")

    assert response.status_code == 200


async def test_control_endpoint_rejects_invalid_expiration_month() -> None:
    response = await _request("/v1/inspeccion/control?month_expiration=13")

    assert response.status_code == 422


async def test_management_endpoint_accepts_last_inspection_date_range() -> None:
    response = await _request(
        "/v1/inspeccion/gestion?fecha_desde=2026-08-01&fecha_hasta=2026-08-31"
    )

    assert response.status_code == 200


async def test_management_endpoint_rejects_inverted_last_inspection_date_range() -> None:
    response = await _request(
        "/v1/inspeccion/gestion?fecha_desde=2026-09-01&fecha_hasta=2026-08-31"
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "fecha_desde no puede ser posterior a fecha_hasta"
    }


async def test_management_endpoint_rejects_invalid_inventory_status_filter() -> None:
    response = await _request("/v1/inspeccion/gestion?estatus_bien_inventario=0")

    assert response.status_code == 422


async def test_management_endpoint_rejects_invalid_province_filter() -> None:
    response = await _request("/v1/inspeccion/gestion?provincia=0")

    assert response.status_code == 422


async def test_management_endpoint_requires_province_for_district() -> None:
    response = await _request("/v1/inspeccion/gestion?distrito=1")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Para filtrar por distrito debe proporcionar provincia"
    }


async def test_management_endpoint_requires_province_and_district_for_township() -> None:
    response = await _request("/v1/inspeccion/gestion?provincia=8&corregimiento=4")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Para filtrar por corregimiento debe proporcionar provincia y distrito"
    }
