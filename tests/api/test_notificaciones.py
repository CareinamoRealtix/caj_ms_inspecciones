import uuid
from datetime import datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.application.notificacion_service import (
    NotificacionAjenaError,
    NotificacionNoActivaError,
    NotificacionNotFoundError,
)
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    UsuarioNotificacion,
    get_notificacion_service,
    get_notificacion_user,
)


class FakeNotificacionService:
    def __init__(self) -> None:
        self.crear_args: dict[str, Any] | None = None
        self.marcar_args: dict[str, Any] | None = None
        self.marcar_exception: Exception | None = None

    async def listar(
        self, email: str, roles: list[str], estado: Any, pagina: int, tamanio: int
    ) -> dict[str, Any]:
        return {
            "data": [
                {
                    "id_notificacion": "00000000-0000-4000-8000-000000000001",
                    "tipo_notificacion": "PROXIMA_A_VENCER",
                    "titulo": "Alerta",
                    "mensaje": "La inspección No. 1 se encuentra próxima a vencer",
                    "referencia_tipo": "INSPECCION",
                    "referencia_id": "00000000-0000-4000-8000-000000000002",
                    "estado": "NO_LEIDA",
                    "fue_vista": False,
                    "icono": "warning",
                    "path": "/inspecciones/1",
                    "modal": False,
                    "creador": "sistema@example.com",
                    "fecha_creacion": datetime(2026, 9, 5, 8, 0).isoformat(),
                    "fecha_vista": None,
                }
            ],
            "pagina": pagina,
            "tamanio": tamanio,
            "total_registros": 1,
            "total_paginas": 1,
            "total_no_leidas": 1,
        }

    async def marcar(
        self, id_notificacion: uuid.UUID, accion: Any, email: str, roles: list[str]
    ) -> None:
        self.marcar_args = {
            "id_notificacion": id_notificacion,
            "accion": accion,
            "email": email,
            "roles": roles,
        }
        if self.marcar_exception is not None:
            raise self.marcar_exception

    async def crear(self, body: Any, creado_por: str | None) -> dict[str, Any]:
        self.crear_args = {"body": body, "creado_por": creado_por}
        return {"id_notificacion": str(uuid.uuid4())}


def _override_usuario(email: str = "inspector@example.com", roles: list[str] | None = None) -> None:
    app.dependency_overrides[get_notificacion_user] = lambda: UsuarioNotificacion(
        email=email, roles=roles or []
    )


async def test_get_notificaciones_returns_service_response() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/notificaciones")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total_no_leidas"] == 1
    assert body["data"][0]["titulo"] == "Alerta"


async def test_patch_notificacion_marks_it_as_vista() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario(roles=["INSPECTOR"])
    id_notificacion = uuid.uuid4()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/v1/inspeccion/notificaciones/{id_notificacion}?accion=vista"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"estado": "vista"}
    assert service.marcar_args["id_notificacion"] == id_notificacion
    assert service.marcar_args["email"] == "inspector@example.com"
    assert service.marcar_args["roles"] == ["INSPECTOR"]


async def test_patch_notificacion_rejects_notification_owned_by_another_user() -> None:
    service = FakeNotificacionService()
    service.marcar_exception = NotificacionAjenaError(uuid.uuid4())
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/v1/inspeccion/notificaciones/{uuid.uuid4()}?accion=silenciada"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_patch_notificacion_returns_404_when_missing() -> None:
    service = FakeNotificacionService()
    service.marcar_exception = NotificacionNotFoundError(uuid.uuid4())
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/v1/inspeccion/notificaciones/{uuid.uuid4()}?accion=vista"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_patch_notificacion_returns_409_when_already_inactive() -> None:
    service = FakeNotificacionService()
    service.marcar_exception = NotificacionNoActivaError(uuid.uuid4())
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/v1/inspeccion/notificaciones/{uuid.uuid4()}?accion=vista"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409


async def test_post_notificacion_with_email_creates_a_single_row() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario(email="sistema@example.com")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/notificaciones",
                json={
                    "email_destinatario": "inspector@example.com",
                    "tipo_notificacion": "ASIGNADA",
                    "titulo": "Nueva inspección",
                    "mensaje": "Se le asignó la inspección No. 10",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert "id_notificacion" in response.json()
    assert service.crear_args["body"].email_destinatario == "inspector@example.com"
    assert service.crear_args["creado_por"] == "sistema@example.com"


async def test_post_notificacion_with_role_creates_a_single_row_without_resolving_members() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario(email="sistema@example.com")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/notificaciones",
                json={
                    "rol": "OFICIAL_BIENES_ADQUIRIDOS",
                    "tipo_notificacion": "TECNICA_REQUERIDA",
                    "titulo": "Inspección técnica requerida",
                    "mensaje": "Se requiere inspección técnica",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert service.crear_args["body"].rol.value == "OFICIAL_BIENES_ADQUIRIDOS"


async def test_post_notificacion_rejects_body_with_both_targets() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    _override_usuario(email="sistema@example.com")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/inspeccion/notificaciones",
                json={
                    "rol": "INSPECTOR",
                    "email_destinatario": "inspector@example.com",
                    "tipo_notificacion": "GENERAL",
                    "titulo": "t",
                    "mensaje": "m",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert service.crear_args is None
