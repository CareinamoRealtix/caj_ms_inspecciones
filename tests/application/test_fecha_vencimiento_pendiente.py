import uuid
from datetime import date
from typing import Any

from app.application.inspeccion_service import InspeccionService
from app.main import app
from app.presentation.api.schemas.inspecciones import (
    FormularioCreateRequest,
    FormularioDetailResponse,
)


class InspectionRepository:
    def __init__(self) -> None:
        self.insert_args: dict[str, Any] | None = None

    async def insert_inspeccion(self, **kwargs: Any) -> int:
        self.insert_args = kwargs
        return 47

    async def get_periodicidad_dias(self, id_periodicidad: int) -> int | None:
        assert id_periodicidad == 6
        return 90

    async def get_active_inspeccion_by_bien_finca(
        self, id_bien_inventario: uuid.UUID, numero_finca: str
    ) -> dict[str, Any] | None:
        return None


def _request() -> FormularioCreateRequest:
    return FormularioCreateRequest(
        id_bien_inventario=uuid.UUID("00000000-0000-4000-8000-000000000002"),
        numero_finca="FINCA-001",
        ruta_id=uuid.UUID("00000000-0000-4000-8000-000000000101"),
        ruta_nombre="Ruta Centro",
        id_tipo_inspeccion=1,
        descripcion_tipo=None,
        email_inspector="inspector@example.com",
        id_periodicidad=6,
        fecha_programada=date(2026, 1, 1),
    )


async def test_create_leaves_expiration_pending_and_persists_periodicity() -> None:
    repository = InspectionRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.crear_inspeccion(_request(), creado_por="creator@example.com")

    assert repository.insert_args is not None
    assert isinstance(repository.insert_args["id_inspeccion"], uuid.UUID)
    assert response.id_inspeccion == repository.insert_args["id_inspeccion"]
    assert "requiere_programacion_automatica" not in repository.insert_args
    assert repository.insert_args["id_periodicidad"] == 6
    assert repository.insert_args["fecha_vencimiento"] is None
    assert "id_inspector" not in repository.insert_args


def test_obsolete_scheduling_fields_are_not_part_of_http_contracts() -> None:
    for field in ("requiere_programacion_automatica",):
        assert field not in FormularioCreateRequest.model_fields
        assert field not in FormularioDetailResponse.model_fields
    assert "id_periodicidad" in FormularioCreateRequest.model_fields
    assert "id_periodicidad" in FormularioDetailResponse.model_fields
    assert "periodicidad" in FormularioDetailResponse.model_fields
    assert "dias_vigencia" in FormularioDetailResponse.model_fields
    assert "id_inspeccion" not in FormularioCreateRequest.model_fields


def test_expiration_remains_available_in_detail() -> None:
    assert FormularioDetailResponse.model_fields["fecha_vencimiento"].is_required()


def test_periodicas_endpoint_is_not_registered() -> None:
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/v1/inspeccion/periodicas" not in paths
    assert "/v1/inspeccion/formulario_id" not in paths
