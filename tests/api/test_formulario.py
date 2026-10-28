import uuid
from datetime import date, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.inspeccion_service import InspeccionService
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    get_azure_ad_client,
    get_inspeccion_service,
)

_ROUTE_ID = "00000000-0000-4000-8000-000000000101"


class CreateInspectionRepository:
    def __init__(self) -> None:
        self.insert_args: dict[str, Any] | None = None
        self.batch_args: dict[str, Any] | None = None
        self.batch_lookup_ids: list[uuid.UUID] | None = None
        self.update_calls: list[dict[str, Any]] = []
        self.upsert_ruta_calls: list[dict[str, Any]] = []
        self.active_lookup_result: dict[str, Any] | None = None

    async def insert_inspeccion(self, **kwargs: Any) -> int:
        self.insert_args = kwargs
        return 47

    async def get_periodicidad_dias(self, id_periodicidad: int) -> int | None:
        return 30 if id_periodicidad == 4 else None

    async def get_active_inspeccion_by_bien_finca(
        self, id_bien_inventario: uuid.UUID, numero_finca: str
    ) -> dict[str, Any] | None:
        return self.active_lookup_result

    async def get_active_batch_targets_for_bienes(
        self, ids: list[uuid.UUID]
    ) -> list[dict[str, Any]]:
        self.batch_lookup_ids = ids
        return []

    async def insert_inspecciones_batch(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.batch_args = kwargs
        return [
            {
                "id_inspeccion": item["id_inspeccion"],
                "numero_inspeccion": 100 + index,
            }
            for index, item in enumerate(kwargs["inspecciones"], start=1)
        ]

    async def update_inspeccion(self, **kwargs: Any) -> int | None:
        self.update_calls.append(kwargs)
        return None

    async def upsert_bien_inventario_ruta(self, **kwargs: Any) -> None:
        self.upsert_ruta_calls.append(kwargs)


class FormCatalogRepository:
    async def get_rutas(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "00000000-0000-4000-8000-000000000101",
                "codigo": "RUTA-001",
                "nombre": "Ruta Centro",
            }
        ]

    async def get_tipos_inspeccion(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "nombre": "Inspección de rutina",
                "descripcion": "Inspección periódica de rutina",
                "permite_descripcion_libre": False,
            }
        ]

    async def get_periodicidades(self) -> list[dict[str, Any]]:
        return [{"id": 4, "nombre": "Mensual", "dias_vigencia": 30}]


class UpdateInspectionRepository:
    def __init__(self, finalizada: bool = False) -> None:
        self.finalizada = finalizada
        self.update_args: dict[str, Any] | None = None

    async def get_inspeccion_lifecycle(self, id_inspeccion: uuid.UUID) -> dict[str, Any]:
        return {
            "activa": not self.finalizada,
            "fecha_realizada": date(2026, 9, 1) if self.finalizada else None,
        }

    async def get_periodicidad_dias(self, id_periodicidad: int) -> int | None:
        return 30

    async def update_inspeccion(self, **kwargs: Any) -> int:
        self.update_args = kwargs
        return 47


class DetailInspectionRepository:
    async def get_inspeccion_by_id(self, id_inspeccion: uuid.UUID) -> dict[str, Any]:
        return {
            "id_inspeccion": id_inspeccion,
            "numero_inspeccion": 47,
            "id_bien_inventario": uuid.UUID("00000000-0000-4000-8000-000000000002"),
            "numero_finca": "FINCA-001",
            "ruta_id": uuid.UUID(_ROUTE_ID),
            "ruta_nombre": "Ruta Centro",
            "id_tipo_inspeccion": 1,
            "tipo_inspeccion": "Inspección de rutina",
            "descripcion_tipo": None,
            "email_inspector": "inspector@example.com",
            "estado_inspeccion": "Activa",
            "id_periodicidad": 4,
            "periodicidad": "Mensual",
            "dias_vigencia": 30,
            "fecha_programada": date(2026, 9, 1),
            "fecha_realizada": None,
            "fecha_vencimiento": date(2026, 10, 1),
            "origen": "WEB",
            "activa": True,
            "creado_por": "local@dev.test",
            "fecha_creacion": datetime(2026, 9, 1, 8, 0),
        }


class FakeAzureAdClient:
    async def get_inspectores(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "user-1",
                "displayName": "Inspector Uno",
                "userPrincipalName": "inspector@example.com",
                "mail": None,
            }
        ]

    async def aclose(self) -> None:
        pass


async def test_create_inspection_generates_id_without_receiving_it_in_body() -> None:
    repository = CreateInspectionRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/formulario",
                headers={"X-User-Email": "local@dev.test"},
                json={
                    "id_bien_inventario": "00000000-0000-4000-8000-000000000002",
                    "numero_finca": "FINCA-001",
                    "ruta_id": _ROUTE_ID,
                    "ruta_nombre": "Ruta Centro",
                    "id_tipo_inspeccion": 1,
                    "descripcion_tipo": None,
                    "email_inspector": "inspector@example.com",
                    "id_periodicidad": 4,
                    "fecha_programada": "2026-09-01",
                },
            )
            openapi = (await client.get("/openapi.json")).json()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    generated_id = uuid.UUID(response.json()["id_inspeccion"])
    assert response.json()["numero_inspeccion"] == 47
    assert repository.insert_args is not None
    assert repository.insert_args["id_inspeccion"] == generated_id
    assert repository.insert_args["fecha_vencimiento"] is None
    assert "/v1/inspeccion/formulario_id" not in openapi["paths"]
    request_schema = openapi["components"]["schemas"]["FormularioCreateRequest"]
    assert "id_inspeccion" not in request_schema["properties"]


async def test_create_inspection_rejects_unknown_periodicity() -> None:
    service = InspeccionService(repo=CreateInspectionRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/formulario",
                headers={"X-User-Email": "local@dev.test"},
                json={
                    "id_bien_inventario": "00000000-0000-4000-8000-000000000002",
                    "numero_finca": "FINCA-001",
                    "ruta_id": _ROUTE_ID,
                    "ruta_nombre": "Ruta Centro",
                    "id_tipo_inspeccion": 1,
                    "email_inspector": "inspector@example.com",
                    "id_periodicidad": 999,
                    "fecha_programada": "2026-09-01",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json() == {"detail": "La periodicidad seleccionada no existe"}


async def test_create_inspection_rejects_when_bien_finca_already_has_an_active_one() -> None:
    repository = CreateInspectionRepository()
    repository.active_lookup_result = {
        "id_inspeccion": uuid.uuid4(),
        "numero_inspeccion": 12,
    }
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/formulario",
                headers={"X-User-Email": "local@dev.test"},
                json={
                    "id_bien_inventario": "00000000-0000-4000-8000-000000000002",
                    "numero_finca": "FINCA-001",
                    "ruta_id": _ROUTE_ID,
                    "ruta_nombre": "Ruta Centro",
                    "id_tipo_inspeccion": 1,
                    "descripcion_tipo": None,
                    "email_inspector": "inspector@example.com",
                    "id_periodicidad": 4,
                    "fecha_programada": "2026-09-01",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "inspección activa" in response.json()["detail"]
    assert repository.insert_args is None


def _update_payload() -> dict[str, Any]:
    return {
        "ruta_id": _ROUTE_ID,
        "ruta_nombre": "Ruta Centro",
        "id_tipo_inspeccion": 1,
        "descripcion_tipo": None,
        "email_inspector": "inspector@example.com",
        "id_periodicidad": 4,
        "fecha_programada": "2026-09-01",
    }


async def test_patch_inspection_edits_without_inventory_identity_fields() -> None:
    repository = UpdateInspectionRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                "/v1/inspeccion/formulario/00000000-0000-4000-8000-000000000010",
                headers={"X-User-Email": "local@dev.test"},
                json=_update_payload(),
            )
            openapi = (await client.get("/openapi.json")).json()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert repository.update_args is not None
    assert "id_bien_inventario" not in repository.update_args
    assert "numero_finca" not in repository.update_args
    assert repository.update_args["fecha_vencimiento"] is None
    schema = openapi["components"]["schemas"]["FormularioUpdateRequest"]
    assert "id_bien_inventario" not in schema["properties"]
    assert "numero_finca" not in schema["properties"]


async def test_patch_inspection_rejects_inventory_identity_fields() -> None:
    repository = UpdateInspectionRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    payload = _update_payload()
    payload["id_bien_inventario"] = "00000000-0000-4000-8000-000000000002"
    payload["numero_finca"] = "FINCA-002"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                "/v1/inspeccion/formulario/00000000-0000-4000-8000-000000000010",
                headers={"X-User-Email": "local@dev.test"},
                json=payload,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert repository.update_args is None


async def test_patch_inspection_rejects_finalized_inspection() -> None:
    repository = UpdateInspectionRepository(finalizada=True)
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                "/v1/inspeccion/formulario/00000000-0000-4000-8000-000000000010",
                headers={"X-User-Email": "local@dev.test"},
                json=_update_payload(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json() == {"detail": "No se puede editar una inspección finalizada"}
    assert repository.update_args is None


async def test_create_inspections_batch_uses_common_assignment_for_all_bienes() -> None:
    repository = CreateInspectionRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/formulario/batch",
                headers={"X-User-Email": "local@dev.test"},
                json={
                    "bienes": [
                        {
                            "id_bien_inventario": "00000000-0000-4000-8000-000000000002",
                            "numero_finca": "FINCA-001",
                        },
                        {
                            "id_bien_inventario": "00000000-0000-4000-8000-000000000003",
                            "numero_finca": "FINCA-002",
                        },
                    ],
                    "ruta_id": _ROUTE_ID,
                    "ruta_nombre": "Ruta Centro",
                    "id_tipo_inspeccion": 1,
                    "descripcion_tipo": None,
                    "email_inspector": "inspector@example.com",
                    "id_periodicidad": 4,
                    "fecha_programada": "2026-09-01",
                },
            )
            openapi = (await client.get("/openapi.json")).json()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["total_creadas"] == 2
    assert [item["numero_finca"] for item in response.json()["inspecciones"]] == [
        "FINCA-001",
        "FINCA-002",
    ]
    assert [item["numero_inspeccion"] for item in response.json()["inspecciones"]] == [
        101,
        102,
    ]
    assert repository.batch_args is not None
    assert repository.batch_lookup_ids is not None
    assert len(repository.batch_lookup_ids) == 2
    assert repository.batch_args["creado_por"] == "local@dev.test"
    inserted = repository.batch_args["inspecciones"]
    assert len(inserted) == 2
    assert all(str(item["ruta_id"]) == _ROUTE_ID for item in inserted)
    assert all(item["fecha_vencimiento"] is None for item in inserted)
    assert "/v1/inspeccion/formulario/batch" in openapi["paths"]
    batch_schema = openapi["components"]["schemas"]["FormularioBatchCreateRequest"]
    assert "maxItems" not in batch_schema["properties"]["bienes"]


async def test_create_inspections_batch_updates_active_and_creates_missing() -> None:
    repository = CreateInspectionRepository()
    active_id = uuid.UUID("00000000-0000-4000-8000-000000009999")

    async def active_for_first_bien(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        repository.batch_lookup_ids = ids
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "FINCA-001",
                "id_inspeccion": active_id,
                "numero_inspeccion": 77,
            }
        ]

    repository.get_active_batch_targets_for_bienes = active_for_first_bien  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/formulario/batch",
                headers={"X-User-Email": "local@dev.test"},
                json={
                    "bienes": [
                        {
                            "id_bien_inventario": "00000000-0000-4000-8000-000000000002",
                            "numero_finca": "FINCA-001",
                        },
                        {
                            "id_bien_inventario": "00000000-0000-4000-8000-000000000003",
                            "numero_finca": "FINCA-002",
                        },
                    ],
                    "ruta_id": _ROUTE_ID,
                    "ruta_nombre": "Ruta Centro",
                    "id_tipo_inspeccion": 1,
                    "descripcion_tipo": None,
                    "email_inspector": "inspector@example.com",
                    "id_periodicidad": 4,
                    "fecha_programada": "2026-09-01",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["total_creadas"] == 2
    assert payload["inspecciones"][0]["id_inspeccion"] == str(active_id)
    assert payload["inspecciones"][0]["numero_inspeccion"] == 77
    assert payload["inspecciones"][1]["numero_inspeccion"] == 101
    assert repository.batch_args is not None
    assert len(repository.batch_args["inspecciones"]) == 1
    assert repository.batch_args["inspecciones"][0]["numero_finca"] == "FINCA-002"
    assert len(repository.update_calls) == 1
    assert repository.update_calls[0]["id_inspeccion"] == active_id
    assert "id_estado_inspeccion" not in repository.update_calls[0]
    assert len(repository.upsert_ruta_calls) == 1
    assert repository.upsert_ruta_calls[0]["id_bien_inventario"] == uuid.UUID(
        "00000000-0000-4000-8000-000000000002"
    )


async def test_create_inspections_batch_accepts_more_than_one_hundred_bienes() -> None:
    repository = CreateInspectionRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    bienes = [
        {
            "id_bien_inventario": f"00000000-0000-4000-8000-{index:012d}",
            "numero_finca": f"FINCA-{index}",
        }
        for index in range(1, 102)
    ]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/formulario/batch",
                headers={"X-User-Email": "local@dev.test"},
                json={
                    "bienes": bienes,
                    "ruta_id": _ROUTE_ID,
                    "ruta_nombre": "Ruta Centro",
                    "id_tipo_inspeccion": 1,
                    "email_inspector": "inspector@example.com",
                    "id_periodicidad": 4,
                    "fecha_programada": "2026-09-01",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["total_creadas"] == 101
    assert repository.batch_args is not None
    assert len(repository.batch_args["inspecciones"]) == 101


async def test_create_inspections_batch_rejects_duplicate_bienes() -> None:
    service = InspeccionService(repo=CreateInspectionRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    bien = {
        "id_bien_inventario": "00000000-0000-4000-8000-000000000002",
        "numero_finca": "FINCA-001",
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/formulario/batch",
                headers={"X-User-Email": "local@dev.test"},
                json={
                    "bienes": [bien, bien],
                    "ruta_id": _ROUTE_ID,
                    "ruta_nombre": "Ruta Centro",
                    "id_tipo_inspeccion": 1,
                    "email_inspector": "inspector@example.com",
                    "id_periodicidad": 4,
                    "fecha_programada": "2026-09-01",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_form_catalogs_returns_all_modal_select_options() -> None:
    service = InspeccionService(repo=FormCatalogRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    app.dependency_overrides[get_azure_ad_client] = FakeAzureAdClient
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/formulario/catalogos")
            openapi = (await client.get("/openapi.json")).json()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "rutas": [
            {
                "id": "00000000-0000-4000-8000-000000000101",
                "codigo": "RUTA-001",
                "nombre": "Ruta Centro",
            }
        ],
        "inspectores": [
            {
                "displayName": "Inspector Uno",
                "mail": "inspector@example.com",
            }
        ],
        "tipos_inspeccion": [
            {
                "id": 1,
                "nombre": "Inspección de rutina",
                "descripcion": "Inspección periódica de rutina",
                "permite_descripcion_libre": False,
            }
        ],
        "periodicidades": [{"id": 4, "nombre": "Mensual", "dias_vigencia": 30}],
    }
    assert "/v1/inspeccion/formulario/catalogos" in openapi["paths"]


async def test_get_form_returns_persisted_periodicity_information() -> None:
    service = InspeccionService(repo=DetailInspectionRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_inspeccion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/inspeccion/formulario/00000000-0000-4000-8000-000000000001"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id_periodicidad"] == 4
    assert data["periodicidad"] == "Mensual"
    assert data["dias_vigencia"] == 30
    assert data["activa"] is True
    assert "id_estado_inspeccion" not in data
    assert "es_activo" not in data
