import uuid
from datetime import datetime
from typing import Any

import pytest

from app.application.notificacion_service import (
    NotificacionAjenaError,
    NotificacionNoActivaError,
    NotificacionNotFoundError,
    NotificacionService,
)
from app.presentation.api.schemas.notificaciones import (
    AccionNotificacion,
    CrearNotificacionRequest,
    EstadoNotificacion,
    RolNotificacion,
)


class FakeRepository:
    def __init__(self) -> None:
        self.list_args: dict[str, Any] | None = None
        self.count_args: dict[str, Any] | None = None
        self.close_previous_args: dict[str, Any] | None = None
        self.insert_args: dict[str, Any] | None = None
        self.marcar_vista_args: tuple[Any, ...] | None = None
        self.marcar_silenciada_args: tuple[Any, ...] | None = None
        self.notificacion: dict[str, Any] | None = None
        self.no_leidas = 3

    async def list_for_user(
        self, email: str, roles: list[str], estados: list[str] | None, pagina: int, tamanio: int
    ) -> tuple[list[dict[str, Any]], int]:
        self.list_args = {
            "email": email,
            "roles": roles,
            "estados": estados,
            "pagina": pagina,
            "tamanio": tamanio,
        }
        return (
            [
                {
                    "id_notificacion": uuid.UUID("00000000-0000-4000-8000-000000000001"),
                    "tipo_notificacion": "PROXIMA_A_VENCER",
                    "titulo": "Alerta",
                    "mensaje": "La inspección No. 1 se encuentra próxima a vencer",
                    "referencia_tipo": "INSPECCION",
                    "referencia_id": uuid.UUID("00000000-0000-4000-8000-000000000002"),
                    "estado": "NO_LEIDA",
                    "fue_vista": False,
                    "icono": "info",
                    "path": None,
                    "modal": False,
                    "creador": "sistema@example.com",
                    "fecha_creacion": datetime(2026, 9, 5, 8, 0),
                    "fecha_vista": None,
                }
            ],
            1,
        )

    async def count_no_leidas(self, email: str, roles: list[str]) -> int:
        self.count_args = {"email": email, "roles": roles}
        return self.no_leidas

    async def get_by_id(self, id_notificacion: uuid.UUID) -> dict[str, Any] | None:
        return self.notificacion

    async def marcar_vista(self, id_notificacion: uuid.UUID, email_lector: str) -> None:
        self.marcar_vista_args = (id_notificacion, email_lector)

    async def marcar_silenciada(self, id_notificacion: uuid.UUID, email_lector: str) -> None:
        self.marcar_silenciada_args = (id_notificacion, email_lector)

    async def close_previous(
        self,
        rol_destino: str | None,
        email_destinatario: str | None,
        referencia_tipo: str,
        referencia_id: uuid.UUID,
        tipo: str,
    ) -> None:
        self.close_previous_args = {
            "rol_destino": rol_destino,
            "email_destinatario": email_destinatario,
            "referencia_tipo": referencia_tipo,
            "referencia_id": referencia_id,
            "tipo": tipo,
        }

    async def insert(self, notificacion: dict[str, Any]) -> dict[str, Any]:
        self.insert_args = notificacion
        return {"id_notificacion": uuid.uuid4()}


def _crear_request(**overrides: Any) -> CrearNotificacionRequest:
    data: dict[str, Any] = {
        "tipo_notificacion": "PROXIMA_A_VENCER",
        "titulo": "Alerta",
        "mensaje": "La inspección No. 1 se encuentra próxima a vencer",
    }
    if "rol" not in overrides and "email_destinatario" not in overrides:
        data["email_destinatario"] = "dummy@example.com"
    data.update(overrides)
    return CrearNotificacionRequest(**data)


async def test_listar_returns_items_and_unread_count() -> None:
    repo = FakeRepository()
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    response = await service.listar(
        "inspector@example.com", ["INSPECTOR"], None, pagina=1, tamanio=15
    )

    assert repo.list_args == {
        "email": "inspector@example.com",
        "roles": ["INSPECTOR"],
        "estados": None,
        "pagina": 1,
        "tamanio": 15,
    }
    assert repo.count_args == {"email": "inspector@example.com", "roles": ["INSPECTOR"]}
    assert response.total_registros == 1
    assert response.total_no_leidas == 3
    assert response.data[0].titulo == "Alerta"


async def test_listar_forwards_explicit_estado_filter() -> None:
    repo = FakeRepository()
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    await service.listar(
        "inspector@example.com", [], EstadoNotificacion.SILENCIADA, pagina=1, tamanio=15
    )

    assert repo.list_args["estados"] == ["SILENCIADA"]


async def test_marcar_rejects_notification_that_does_not_exist() -> None:
    repo = FakeRepository()
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    with pytest.raises(NotificacionNotFoundError):
        await service.marcar(
            uuid.uuid4(), AccionNotificacion.VISTA, "inspector@example.com", []
        )


async def test_marcar_rejects_notification_that_matches_neither_email_nor_role() -> None:
    repo = FakeRepository()
    repo.notificacion = {
        "id_notificacion": uuid.uuid4(),
        "rol_destino": None,
        "email_destinatario": "otro@example.com",
        "estado_notificacion": "ACTIVA",
    }
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    with pytest.raises(NotificacionAjenaError):
        await service.marcar(
            uuid.uuid4(), AccionNotificacion.VISTA, "inspector@example.com", ["INSPECTOR"]
        )

    assert repo.marcar_vista_args is None
    assert repo.marcar_silenciada_args is None


async def test_marcar_accepts_notification_matched_by_role() -> None:
    repo = FakeRepository()
    id_notificacion = uuid.uuid4()
    repo.notificacion = {
        "id_notificacion": id_notificacion,
        "rol_destino": "INSPECTOR",
        "email_destinatario": None,
        "estado_notificacion": "ACTIVA",
    }
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    await service.marcar(
        id_notificacion, AccionNotificacion.VISTA, "inspector@example.com", ["INSPECTOR"]
    )

    assert repo.marcar_vista_args == (id_notificacion, "inspector@example.com")


async def test_marcar_rejects_notification_already_closed() -> None:
    repo = FakeRepository()
    repo.notificacion = {
        "id_notificacion": uuid.uuid4(),
        "rol_destino": None,
        "email_destinatario": "inspector@example.com",
        "estado_notificacion": "CERRADA",
    }
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    with pytest.raises(NotificacionNoActivaError):
        await service.marcar(
            uuid.uuid4(), AccionNotificacion.SILENCIADA, "inspector@example.com", []
        )


async def test_marcar_vista_updates_estado_and_fecha_vista() -> None:
    repo = FakeRepository()
    id_notificacion = uuid.uuid4()
    repo.notificacion = {
        "id_notificacion": id_notificacion,
        "rol_destino": None,
        "email_destinatario": "inspector@example.com",
        "estado_notificacion": "ACTIVA",
    }
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    await service.marcar(id_notificacion, AccionNotificacion.VISTA, "inspector@example.com", [])

    assert repo.marcar_vista_args == (id_notificacion, "inspector@example.com")
    assert repo.marcar_silenciada_args is None


async def test_marcar_silenciada_updates_estado_and_fecha_silenciada() -> None:
    repo = FakeRepository()
    id_notificacion = uuid.uuid4()
    repo.notificacion = {
        "id_notificacion": id_notificacion,
        "rol_destino": None,
        "email_destinatario": "inspector@example.com",
        "estado_notificacion": "ACTIVA",
    }
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]

    await service.marcar(
        id_notificacion, AccionNotificacion.SILENCIADA, "inspector@example.com", []
    )

    assert repo.marcar_silenciada_args == (id_notificacion, "inspector@example.com")
    assert repo.marcar_vista_args is None


async def test_crear_closes_previous_notifications_sharing_the_same_reference() -> None:
    repo = FakeRepository()
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]
    referencia_id = uuid.uuid4()
    body = _crear_request(
        email_destinatario="inspector@example.com",
        referencia_tipo="INSPECCION",
        referencia_id=referencia_id,
    )

    response = await service.crear(body, creado_por="sistema@example.com")

    assert repo.close_previous_args == {
        "rol_destino": None,
        "email_destinatario": "inspector@example.com",
        "referencia_tipo": "INSPECCION",
        "referencia_id": referencia_id,
        "tipo": "PROXIMA_A_VENCER",
    }
    assert repo.insert_args == {
        "rol_destino": None,
        "email_destinatario": "inspector@example.com",
        "tipo_notificacion": "PROXIMA_A_VENCER",
        "titulo": "Alerta",
        "mensaje": "La inspección No. 1 se encuentra próxima a vencer",
        "referencia_tipo": "INSPECCION",
        "referencia_id": referencia_id,
        "creado_por": "sistema@example.com",
    }
    assert response.id_notificacion is not None


async def test_crear_skips_close_previous_without_a_reference() -> None:
    repo = FakeRepository()
    service = NotificacionService(repo=repo)  # type: ignore[arg-type]
    body = _crear_request(rol=RolNotificacion.INSPECTOR)

    await service.crear(body, creado_por=None)

    assert repo.close_previous_args is None
    assert repo.insert_args["rol_destino"] == "INSPECTOR"
    assert repo.insert_args["email_destinatario"] is None


async def test_crear_notificacion_request_requires_exactly_one_target() -> None:
    with pytest.raises(ValueError):
        CrearNotificacionRequest(tipo_notificacion="GENERAL", titulo="t", mensaje="m")

    with pytest.raises(ValueError):
        _crear_request(rol=RolNotificacion.INSPECTOR, email_destinatario="a@example.com")

    _crear_request(rol=RolNotificacion.INSPECTOR)
    _crear_request(email_destinatario="a@example.com")
