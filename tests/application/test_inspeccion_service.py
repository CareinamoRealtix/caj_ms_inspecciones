import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.application.gestion_catalogos import AlertaGestion
from app.application.inspeccion_service import (
    GestionDateFiltersError,
    GestionLocationFiltersError,
    InspeccionService,
    _classify_control_inspection_status,
    _orden_vencimiento,
)
from app.presentation.api.schemas.inspectores import InspectorItem


def _per_finca(rows: list[dict[str, Any]], fincas: list[str]) -> list[dict[str, Any]]:
    """Imita la paginación del repositorio: una fila por (bien, finca)."""
    return [{**row, "numero_finca_item": finca} for row in rows for finca in fincas]


class InventoryRepository:
    def __init__(self) -> None:
        self.last_inventory_args: dict[str, Any] | None = None

    async def get_inventario(self, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        self.last_inventory_args = kwargs
        return (
            [
                {
                    "id_bien_inventario": uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d"),
                    "id_bien": uuid.UUID("e7365a7d-8356-4186-9db7-bbfa72fe8254"),
                    "no_registro": 3333,
                    "numero_finca": "100-200",
                    "numero_finca_item": "100-200",
                    "numeros_finca": ["100", "200"],
                    "nombre_deudor": None,
                    "numero_prestamo": None,
                    "id_tipo_propiedad": 1,
                    "tipo_propiedad": "Terreno",
                    "id_provincia": 8,
                    "provincia": "Panamá",
                    "id_distrito": 1,
                    "distrito": "Panamá",
                    "id_corregimiento": 4,
                    "corregimiento": "Bella Vista",
                    "barriada_sector": "El Carmen",
                    "direccion": "Calle 50, Edificio 1",
                    "numero_lote": "12",
                    "latitud": 8.9833,
                    "longitud": -79.5167,
                    "url_ubicacion_geoespacial": "https://maps.example/ubicacion",
                    "monto_adjudicado": Decimal("200000.00"),
                    "valor_avaluo": Decimal("0.00"),
                    "estatus_bien": "En Venta",
                    "color_badge": "#28a745",
                    "estado_inventario": "borrador",
                    "oficinista": "Anthony H.",
                    "usuario_registrador": "inspector@example.com",
                    "fecha_recibido_inventario": date(2026, 8, 25),
                    "fecha_creacion": datetime(2026, 8, 25, 10, 30),
                }
            ],
            1,
        )

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
                "id": uuid.UUID("00000000-0000-4000-8000-000000000101"),
                "codigo": "RUTA-001",
                "nombre": "Ruta Centro",
            }
        ]

    async def get_active_inspections_for_bienes(self, ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        assert ids == [uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d")]
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100-200",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000001"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 1),
                "fecha_vencimiento": date(2026, 10, 1),
                "descripcion_tipo": "Revisión de humedad",
            }
        ]

    async def get_latest_completed_inspections_for_bienes(
        self, ids: list[uuid.UUID]
    ) -> list[dict[str, Any]]:
        assert ids == [uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d")]
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100-200",
                "numero_inspeccion": 666,
                "fecha_realizada": date(2026, 8, 28),
                "fecha_vencimiento": date(2026, 9, 27),
            }
        ]

    async def get_bien_inventario_rutas_for_bienes(
        self, ids: list[uuid.UUID]
    ) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100-200",
                "id_ruta": uuid.UUID("00000000-0000-4000-8000-000000000101"),
                "ruta_nombre": "Ruta Centro",
            }
        ]


async def test_get_gestion_reads_view_data_and_enriches_inspection() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=4,
        provincia=8,
        distrito=1,
        corregimiento=4,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["id_estatus_bien"] == 4
    assert repository.last_inventory_args["id_provincia"] == 8
    assert repository.last_inventory_args["id_distrito"] == 1
    assert repository.last_inventory_args["id_corregimiento"] == 4
    assert repository.last_inventory_args["nuevo_ingreso"] is False
    assert repository.last_inventory_args["alerta"] is None
    assert repository.last_inventory_args["ruta"] is None
    assert repository.last_inventory_args["month_last_insp"] is None
    assert repository.last_inventory_args["fecha_desde"] is None
    assert repository.last_inventory_args["fecha_hasta"] is None
    assert response.data[0].numero_finca == "100-200"
    assert response.data[0].numeros_finca == ["100", "200"]
    assert response.data[0].id_bien_inventario == uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d")
    assert response.data[0].provincia == "Panamá"
    assert response.data[0].distrito == "Panamá"
    assert response.data[0].corregimiento == "Bella Vista"
    assert response.data[0].barriada_sector == "El Carmen"
    assert response.data[0].direccion == "Calle 50, Edificio 1"
    assert response.data[0].numero_lote == "12"
    assert response.data[0].latitud == 8.9833
    assert response.data[0].longitud == -79.5167
    assert response.data[0].url_ubicacion_geoespacial == "https://maps.example/ubicacion"
    assert response.data[0].fecha_creacion == datetime(2026, 8, 25, 10, 30)
    assert response.data[0].ruta_id == uuid.UUID("00000000-0000-4000-8000-000000000101")
    assert response.data[0].ruta_nombre == "Ruta Centro"
    assert response.data[0].monto_adjudicado == Decimal("200000.00")
    assert response.data[0].tiene_inspeccion_activa is True
    assert response.data[0].estado_inspeccion == "Activa"
    assert response.data[0].numero_inspeccion is None
    assert response.data[0].color_badge_inspeccion == "#inspection"
    assert response.data[0].fecha_realizada == date(2026, 8, 28)
    assert response.data[0].fecha_vencimiento == date(2026, 10, 1)
    assert response.data[0].inspeccion_descripcion_tipo == "Revisión de humedad"
    assert response.total_registros == 1
    assert response.total_paginas == 1


async def test_get_gestion_returns_active_expiration_without_completed_inspection() -> None:
    repository = InventoryRepository()

    async def no_completed_inspections(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        assert ids == [uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d")]
        return []

    repository.get_latest_completed_inspections_for_bienes = no_completed_inspections  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    assert response.data[0].fecha_realizada is None
    assert response.data[0].fecha_vencimiento == date(2026, 10, 1)


async def test_get_gestion_prefers_last_completed_expiration_when_active_has_none() -> None:
    repository = InventoryRepository()
    get_inventario = repository.get_inventario

    async def inventory_with_order_expiration(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await get_inventario(**kwargs)
        rows[0]["fecha_vencimiento_orden"] = date(2026, 8, 1)
        return rows, total

    async def active_with_pending_expiration(
        ids: list[uuid.UUID],
    ) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100-200",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000001"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 1),
                "fecha_vencimiento": None,
            }
        ]

    repository.get_active_inspections_for_bienes = active_with_pending_expiration  # type: ignore[method-assign]
    repository.get_inventario = inventory_with_order_expiration  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    assert response.data[0].fecha_vencimiento == date(2026, 9, 27)


async def test_get_gestion_emits_row_per_finca_with_multiple_inspections() -> None:
    repository = InventoryRepository()
    get_inventario = repository.get_inventario

    async def inventory_with_plain_finca_list(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await get_inventario(**kwargs)
        rows[0]["numero_finca"] = "100-200"
        rows[0]["numeros_finca"] = ["100", "200"]
        return _per_finca(rows, ["100", "200"]), total

    async def active_per_finca(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000011"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 1),
                "fecha_vencimiento": date(2026, 10, 1),
            },
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "200",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000012"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 2),
                "fecha_vencimiento": date(2026, 10, 2),
            },
        ]

    async def latest_per_finca(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100",
                "fecha_realizada": date(2026, 8, 15),
                "fecha_vencimiento": date(2026, 9, 15),
            },
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "200",
                "fecha_realizada": date(2026, 8, 16),
                "fecha_vencimiento": date(2026, 9, 16),
            },
        ]

    repository.get_inventario = inventory_with_plain_finca_list  # type: ignore[method-assign]
    repository.get_active_inspections_for_bienes = active_per_finca  # type: ignore[method-assign]
    repository.get_latest_completed_inspections_for_bienes = latest_per_finca  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    assert len(response.data) == 2
    assert [item.numero_finca for item in response.data] == ["100", "200"]
    assert response.data[0].id_inspeccion == uuid.UUID("00000000-0000-4000-8000-000000000011")
    assert response.data[1].id_inspeccion == uuid.UUID("00000000-0000-4000-8000-000000000012")


async def test_get_gestion_filters_using_inspection_finca_when_view_is_outdated() -> None:
    repository = InventoryRepository()
    get_inventario = repository.get_inventario

    async def inventory_with_outdated_finca(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await get_inventario(**kwargs)
        rows[0]["numero_finca"] = "15963"
        rows[0]["numeros_finca"] = ["15963"]
        return _per_finca(rows, ["3099"]), total

    async def active_with_current_finca(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "3099",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000011"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 1),
                "fecha_vencimiento": None,
            }
        ]

    async def no_completed(_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return []

    repository.get_inventario = inventory_with_outdated_finca  # type: ignore[method-assign]
    repository.get_active_inspections_for_bienes = active_with_current_finca  # type: ignore[method-assign]
    repository.get_latest_completed_inspections_for_bienes = no_completed  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=" 3099 ",
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["numero_finca"] == "3099"
    assert [item.numero_finca for item in response.data] == ["3099"]


async def test_get_gestion_uses_expiration_per_finca_when_available() -> None:
    repository = InventoryRepository()
    get_inventario = repository.get_inventario

    async def inventory_with_global_order_expiration(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await get_inventario(**kwargs)
        rows[0]["fecha_vencimiento_orden"] = date(2026, 8, 1)
        rows[0]["numeros_finca"] = ["3344", "107005"]
        return _per_finca(rows, ["3344", "107005"]), total

    async def active_per_finca(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "107005",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000021"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 3),
                "fecha_vencimiento": date(2026, 9, 4),
            },
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "3344",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000022"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 1),
                "fecha_vencimiento": date(2026, 8, 1),
            },
        ]

    async def no_completed(_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return []

    repository.get_inventario = inventory_with_global_order_expiration  # type: ignore[method-assign]
    repository.get_active_inspections_for_bienes = active_per_finca  # type: ignore[method-assign]
    repository.get_latest_completed_inspections_for_bienes = no_completed  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    expiration_by_finca = {
        item.numero_finca: item.fecha_vencimiento for item in response.data
    }
    assert expiration_by_finca["107005"] == date(2026, 9, 4)
    assert expiration_by_finca["3344"] == date(2026, 8, 1)


async def test_get_gestion_does_not_mix_up_route_assignments_across_fincas_of_same_bien() -> None:
    repository = InventoryRepository()
    get_inventario = repository.get_inventario

    async def inventory_with_plain_finca_list(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await get_inventario(**kwargs)
        rows[0]["numero_finca"] = "100-200"
        rows[0]["numeros_finca"] = ["100", "200"]
        return _per_finca(rows, ["100", "200"]), total

    async def no_inspections(_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return []

    async def rutas_per_finca(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100",
                "id_ruta": uuid.UUID("00000000-0000-4000-8000-000000000101"),
                "ruta_nombre": "Ruta Centro",
            },
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "200",
                "id_ruta": uuid.UUID("00000000-0000-4000-8000-000000000102"),
                "ruta_nombre": "Ruta Este",
            },
        ]

    repository.get_inventario = inventory_with_plain_finca_list  # type: ignore[method-assign]
    repository.get_active_inspections_for_bienes = no_inspections  # type: ignore[method-assign]
    repository.get_latest_completed_inspections_for_bienes = no_inspections  # type: ignore[method-assign]
    repository.get_bien_inventario_rutas_for_bienes = rutas_per_finca  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    ruta_by_finca = {item.numero_finca: item.ruta_nombre for item in response.data}
    assert ruta_by_finca == {"100": "Ruta Centro", "200": "Ruta Este"}


async def test_get_gestion_forwards_new_entry_filter() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
        nuevo_ingreso=True,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["nuevo_ingreso"] is True


async def test_get_gestion_forwards_alert_filter() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
        alerta=AlertaGestion.PROXIMA,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["alerta"] == AlertaGestion.PROXIMA


async def test_get_gestion_forwards_route_filter() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    route_id = uuid.UUID("00000000-0000-4000-8000-000000000101")

    await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
        ruta=route_id,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["ruta"] == route_id


async def test_get_gestion_forwards_last_inspection_month_filter() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
        month_last_insp=8,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["month_last_insp"] == f"{date.today().year}-08"


async def test_get_gestion_forwards_last_inspection_date_range() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
        fecha_desde=date(2026, 8, 1),
        fecha_hasta=date(2026, 8, 31),
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["fecha_desde"] == date(2026, 8, 1)
    assert repository.last_inventory_args["fecha_hasta"] == date(2026, 8, 31)


async def test_get_control_reuses_management_without_excluded_filters() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]
    inspector_email = "inspector@example.com"

    await service.get_control(
        pagina=1,
        tamanio=15,
        numero_finca="FINCA-001",
        estatus_bien_inventario=4,
        provincia=8,
        distrito=1,
        corregimiento=4,
        alerta=AlertaGestion.VENCIDA,
        inspector=inspector_email,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["id_estatus_bien"] == 4
    assert repository.last_inventory_args["nuevo_ingreso"] is False
    assert repository.last_inventory_args["requiere_inspeccion_finalizada"] is True
    assert repository.last_inventory_args["ruta"] is None
    assert repository.last_inventory_args["alerta"] == AlertaGestion.VENCIDA
    assert repository.last_inventory_args["inspector"] == inspector_email


async def test_get_control_forwards_expiration_month_filter() -> None:
    repository = InventoryRepository()
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    await service.get_control(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
        month_expiration=8,
    )

    assert repository.last_inventory_args is not None
    assert repository.last_inventory_args["month_last_insp"] is None
    assert repository.last_inventory_args["month_expiration"] == f"{date.today().year}-08"


@pytest.mark.parametrize(
    ("expiration", "expected"),
    [
        (date(2026, 9, 7), "VENCIDA"),
        (date(2026, 9, 8), "PROXIMA"),
        (date(2026, 9, 18), "PROXIMA"),
        (date(2026, 9, 19), "TERMINO"),
        (None, None),
    ],
)
def test_control_inspection_status_uses_expiration_boundaries(
    expiration: date | None,
    expected: str | None,
) -> None:
    assert (
        _classify_control_inspection_status(
            expiration,
            reference_date=date(2026, 9, 8),
        )
        == expected
    )


async def test_get_control_returns_calculated_inspection_status() -> None:
    repository = InventoryRepository()
    get_active = repository.get_active_inspections_for_bienes
    get_completed = repository.get_latest_completed_inspections_for_bienes

    async def active_without_expiration(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        rows = await get_active(ids)
        rows[0]["fecha_vencimiento"] = None
        return rows

    async def completed_near_expiration(
        ids: list[uuid.UUID],
    ) -> list[dict[str, Any]]:
        rows = await get_completed(ids)
        rows[0]["fecha_vencimiento"] = date.today() + timedelta(days=5)
        return rows

    repository.get_active_inspections_for_bienes = active_without_expiration  # type: ignore[method-assign]
    repository.get_latest_completed_inspections_for_bienes = completed_near_expiration  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_control(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    item = next(i for i in response.data if i.numero_finca == "100-200")
    assert item.fecha_vencimiento == date.today() + timedelta(days=5)
    assert item.numero_inspeccion == "INSP-666"
    assert item.estado_inspeccion == "PROXIMA"


@pytest.mark.parametrize(
    ("dias", "estado", "color"),
    [
        (-1, "VENCIDA", "#dc3545"),
        (5, "PROXIMA", "#ffc107"),
        (30, "TERMINO", "#28a745"),
        (None, None, None),
    ],
)
async def test_get_gestion_returns_alert_state_and_color(
    dias: int | None, estado: str | None, color: str | None
) -> None:
    repository = InventoryRepository()
    get_active = repository.get_active_inspections_for_bienes
    get_completed = repository.get_latest_completed_inspections_for_bienes

    async def active_without_expiration(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        rows = await get_active(ids)
        rows[0]["fecha_vencimiento"] = None
        return rows

    async def completed_with_expiration(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        rows = await get_completed(ids)
        rows[0]["fecha_vencimiento"] = (
            date.today() + timedelta(days=dias) if dias is not None else None
        )
        return rows

    repository.get_active_inspections_for_bienes = active_without_expiration  # type: ignore[method-assign]
    repository.get_latest_completed_inspections_for_bienes = completed_with_expiration  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    item = next(i for i in response.data if i.numero_finca == "100-200")
    assert item.estado_alerta == estado
    assert item.color_alerta == color
    # estado_inspeccion conserva su significado propio en /gestion
    assert item.estado_inspeccion != "VENCIDA"


async def test_get_control_includes_fincas_without_any_inspection() -> None:
    repository = InventoryRepository()
    get_inventario = repository.get_inventario
    get_active = repository.get_active_inspections_for_bienes

    async def active_with_uncompleted_finca(
        ids: list[uuid.UUID],
    ) -> list[dict[str, Any]]:
        rows = await get_active(ids)
        rows.append(
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "ACTIVE-ONLY",
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000099"),
                "estado_inspeccion": "Activa",
                "color_badge": "#inspection",
                "fecha_programada": date(2026, 9, 20),
                "fecha_vencimiento": None,
            }
        )
        return rows

    async def inventory_with_every_finca(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await get_inventario(**kwargs)
        return _per_finca(rows, ["100-200", "ACTIVE-ONLY", "100", "200"]), total

    repository.get_inventario = inventory_with_every_finca  # type: ignore[method-assign]
    repository.get_active_inspections_for_bienes = active_with_uncompleted_finca  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_control(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    fincas_por_numero = {item.numero_finca: item for item in response.data}
    # Ahora se incluyen TODAS las fincas del bien: la que ya tiene inspección
    # finalizada ("100-200"), la que solo tiene una activa sin finalizar
    # ("ACTIVE-ONLY"), y las que nunca tuvieron ninguna ("100", "200").
    assert set(fincas_por_numero) == {"100-200", "ACTIVE-ONLY", "100", "200"}
    assert fincas_por_numero["100-200"].numero_inspeccion == "INSP-666"
    assert fincas_por_numero["ACTIVE-ONLY"].numero_inspeccion is None
    assert fincas_por_numero["100"].numero_inspeccion is None
    assert fincas_por_numero["200"].numero_inspeccion is None


async def test_get_gestion_rejects_inverted_last_inspection_date_range() -> None:
    service = InspeccionService(repo=InventoryRepository())  # type: ignore[arg-type]

    with pytest.raises(GestionDateFiltersError, match="fecha_desde"):
        await service.get_gestion(
            pagina=1,
            tamanio=15,
            numero_finca=None,
            estatus_bien_inventario=None,
            provincia=None,
            distrito=None,
            corregimiento=None,
            fecha_desde=date(2026, 9, 1),
            fecha_hasta=date(2026, 8, 31),
        )


async def test_get_gestion_rejects_district_without_province() -> None:
    service = InspeccionService(repo=InventoryRepository())  # type: ignore[arg-type]

    with pytest.raises(GestionLocationFiltersError, match="debe proporcionar provincia"):
        await service.get_gestion(
            pagina=1,
            tamanio=15,
            numero_finca=None,
            estatus_bien_inventario=None,
            provincia=None,
            distrito=1,
            corregimiento=None,
        )


async def test_get_gestion_rejects_township_without_full_location_hierarchy() -> None:
    service = InspeccionService(repo=InventoryRepository())  # type: ignore[arg-type]

    with pytest.raises(GestionLocationFiltersError, match="provincia y distrito"):
        await service.get_gestion(
            pagina=1,
            tamanio=15,
            numero_finca=None,
            estatus_bien_inventario=None,
            provincia=8,
            distrito=None,
            corregimiento=4,
        )


async def test_get_catalogos_gestion_combines_view_catalogs_and_graph_inspectors() -> None:
    service = InspeccionService(repo=InventoryRepository())  # type: ignore[arg-type]

    response = await service.get_catalogos_gestion(
        [
            InspectorItem(
                displayName="Inspector 1",
                mail="inspector@example.com",
            )
        ]
    )

    assert response.inspectores[0].model_dump() == {
        "displayName": "Inspector 1",
        "mail": "inspector@example.com",
    }
    assert response.estatus_bien_inventario[0].model_dump() == {
        "id": 1,
        "estado": "Ocupado",
    }
    assert all(item.id != 6 for item in response.estatus_bien_inventario)
    assert response.alertas == ["TERMINO", "VENCIDA", "PROXIMA"]
    assert response.provincias[0].model_dump() == {"id": 8, "nombre": "Panamá"}
    assert response.distritos[0].model_dump() == {
        "id": 1,
        "nombre": "Panamá",
        "id_provincia": 8,
    }
    assert response.corregimientos[0].model_dump() == {
        "id": 4,
        "nombre": "Bella Vista",
        "id_distrito": 1,
    }
    assert response.rutas[0].model_dump() == {
        "id": uuid.UUID("00000000-0000-4000-8000-000000000101"),
        "codigo": "RUTA-001",
        "nombre": "Ruta Centro",
    }


class HistoricoRepository:
    def __init__(self, numeros_inspeccion: list[int | None]) -> None:
        self._numeros_inspeccion = numeros_inspeccion

    async def get_historico_by_finca(
        self, numero_finca: str | None, pagina: int, tamanio: int, **kwargs: Any
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [
            {
                "id_bien_inventario": uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d"),
                "id_bien": None,
                "no_registro": 1,
                "numero_finca": numero_finca,
                "numeros_finca": [numero_finca],
                "nombre_deudor": None,
                "numero_prestamo": None,
                "id_tipo_propiedad": None,
                "tipo_propiedad": None,
                "id_provincia": None,
                "provincia": None,
                "id_distrito": None,
                "distrito": None,
                "id_corregimiento": None,
                "corregimiento": None,
                "barriada_sector": None,
                "direccion": None,
                "numero_lote": None,
                "latitud": None,
                "longitud": None,
                "url_ubicacion_geoespacial": None,
                "monto_adjudicado": None,
                "valor_avaluo": None,
                "estatus_bien": None,
                "bien_color_badge": None,
                "estado_inventario": None,
                "oficinista": None,
                "usuario_registrador": None,
                "fecha_recibido_inventario": None,
                "id_inspeccion": uuid.UUID("00000000-0000-4000-8000-000000000001"),
                "ruta_id": None,
                "ruta_nombre": None,
                "id_periodicidad": None,
                "periodicidad": None,
                "tipo_inspeccion": None,
                "descripcion_tipo": None,
                "email_inspector": "inspector@example.com",
                "fecha_programada": date(2026, 9, 1),
                "fecha_realizada": date(2026, 9, 2),
                "fecha_vencimiento": date(2026, 10, 2),
                "fecha_creacion": datetime(2026, 8, 31, 10, 30),
                "fecha_modificacion": datetime(2026, 9, 2, 12, 0),
                "activa": False,
                "estado_inspeccion": "Finalizada",
                "color_badge_inspeccion": None,
                "numero_inspeccion": numero,
            }
            for numero in self._numeros_inspeccion
        ]
        return rows, len(rows)


async def test_get_historico_formats_numero_inspeccion_with_insp_prefix() -> None:
    service = InspeccionService(
        repo=HistoricoRepository([1, 666, 5369, None])  # type: ignore[arg-type]
    )

    response = await service.get_historico(
        numero_finca="100-200", pagina=1, tamanio=15
    )

    assert [item.numero_inspeccion for item in response.data] == [
        "INSP-001",
        "INSP-666",
        "INSP-5369",
        None,
    ]


async def test_get_historico_returns_only_summary_and_inspection_dates() -> None:
    service = InspeccionService(
        repo=HistoricoRepository([1])  # type: ignore[arg-type]
    )

    response = await service.get_historico(
        numero_finca="100-200", pagina=1, tamanio=15
    )

    assert set(response.data[0].model_dump()) == {
        "id_inspeccion",
        "id_bien_inventario",
        "numero_finca",
        "numero_inspeccion",
        "email_inspector",
        "fecha_programada",
        "fecha_realizada",
        "fecha_vencimiento",
        "fecha_creacion",
        "fecha_modificacion",
        "activa",
        "estado_inspeccion",
    }
    assert response.data[0].id_inspeccion == uuid.UUID(
        "00000000-0000-4000-8000-000000000001"
    )


async def test_get_historico_normalizes_finca_before_exact_filter() -> None:
    service = InspeccionService(
        repo=HistoricoRepository([1])  # type: ignore[arg-type]
    )

    response = await service.get_historico(
        numero_finca=" 100-200 ", pagina=1, tamanio=15
    )

    assert response.data[0].numero_finca == "100-200"


async def test_get_historico_propagates_none_when_numero_finca_is_blank() -> None:
    class CapturingRepository(HistoricoRepository):
        received: Any = "unset"

        async def get_historico_by_finca(  # type: ignore[override]
            self, numero_finca: str | None, pagina: int, tamanio: int, **kwargs: Any
        ) -> tuple[list[dict[str, Any]], int]:
            self.received = numero_finca
            return [], 0

    repo = CapturingRepository([])
    service = InspeccionService(repo=repo)  # type: ignore[arg-type]

    await service.get_historico(
        numero_finca="  ", pagina=1, tamanio=15, inspector="a@b.com"
    )

    assert repo.received is None


async def test_get_historico_rejects_inverted_date_range() -> None:
    service = InspeccionService(repo=HistoricoRepository([1]))  # type: ignore[arg-type]

    with pytest.raises(GestionDateFiltersError, match="fecha_desde"):
        await service.get_historico(
            numero_finca="100-200",
            pagina=1,
            tamanio=15,
            fecha_desde=date(2026, 9, 1),
            fecha_hasta=date(2026, 8, 31),
        )


class DetalleRepository:
    def __init__(self) -> None:
        self.id_inspeccion = uuid.UUID("00000000-0000-4000-8000-000000000001")

    async def get_detalle(self, id_inspeccion: uuid.UUID) -> dict[str, Any] | None:
        return {
            "id_inspeccion": self.id_inspeccion,
            "numero_inspeccion": 1,
            "numero_finca": "304826291",
            "id_bien_inventario": uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d"),
            "ruta_id": uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3e"),
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
            "direccion": "Calle Principal / Casa 215",
            "numero_lote": None,
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

    async def get_fotografias_by_inspeccion(self, id_inspeccion: uuid.UUID) -> list[Any]:
        return []


async def test_get_detalle_maps_property_location_fields_from_inventory_view() -> None:
    service = InspeccionService(repo=DetalleRepository())  # type: ignore[arg-type]

    detalle = await service.get_detalle(
        uuid.UUID("00000000-0000-4000-8000-000000000001")
    )

    assert detalle.provincia == "Panamá"
    assert detalle.distrito == "Panamá"
    assert detalle.corregimiento == "Pacora"
    assert detalle.barriada_sector == "Residencial Mirador del Bosque"
    assert detalle.direccion == "Calle Principal / Casa 215"
    assert detalle.numero_lote is None


def test_orden_vencimiento_agrupa_vencidas_proximas_termino_y_sin_fecha() -> None:
    hoy = date(2026, 10, 1)
    fechas = [
        None,
        hoy + timedelta(days=30),
        hoy + timedelta(days=11),
        hoy + timedelta(days=10),
        hoy,
        hoy - timedelta(days=1),
        hoy - timedelta(days=40),
        hoy + timedelta(days=3),
    ]

    ordenadas = sorted(fechas, key=lambda f: _orden_vencimiento(f, reference_date=hoy))

    assert ordenadas == [
        hoy - timedelta(days=40),  # vencidas: la más vencida primero
        hoy - timedelta(days=1),
        hoy,  # próximas: la que vence antes primero
        hoy + timedelta(days=3),
        hoy + timedelta(days=10),
        hoy + timedelta(days=11),  # a término: la más cercana primero
        hoy + timedelta(days=30),
        None,  # sin fecha al final
    ]


async def test_get_gestion_orders_fincas_of_a_bien_by_vencimiento_group() -> None:
    repository = InventoryRepository()
    get_inventario = repository.get_inventario
    hoy = date.today()

    async def inventory_with_three_fincas(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await get_inventario(**kwargs)
        rows[0]["numero_finca"] = "100-200-300"
        rows[0]["numeros_finca"] = ["100", "200", "300"]
        return _per_finca(rows, ["100", "200", "300"]), total

    async def no_active(_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return []

    async def completed(ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        return [
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "100",
                "fecha_realizada": hoy,
                "fecha_vencimiento": hoy + timedelta(days=60),
            },
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "200",
                "fecha_realizada": hoy,
                "fecha_vencimiento": hoy - timedelta(days=5),
            },
            {
                "id_bien_inventario": ids[0],
                "numero_finca": "300",
                "fecha_realizada": hoy,
                "fecha_vencimiento": hoy + timedelta(days=4),
            },
        ]

    repository.get_inventario = inventory_with_three_fincas  # type: ignore[method-assign]
    repository.get_active_inspections_for_bienes = no_active  # type: ignore[method-assign]
    repository.get_latest_completed_inspections_for_bienes = completed  # type: ignore[method-assign]
    service = InspeccionService(repo=repository)  # type: ignore[arg-type]

    response = await service.get_gestion(
        pagina=1,
        tamanio=15,
        numero_finca=None,
        estatus_bien_inventario=None,
        provincia=None,
        distrito=None,
        corregimiento=None,
    )

    assert [item.numero_finca for item in response.data] == ["200", "300", "100"]
