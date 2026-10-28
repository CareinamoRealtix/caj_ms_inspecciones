import time
from typing import Any

import jwt
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.presentation.api.dependencies.inspecciones import get_notificacion_service


class FakeNotificacionService:
    def __init__(self) -> None:
        self.listar_args: dict[str, Any] | None = None

    async def listar(
        self, email: str, roles: list[str], estado: Any, pagina: int, tamanio: int
    ) -> dict[str, Any]:
        self.listar_args = {"email": email, "roles": roles, "estado": estado}
        return {
            "data": [],
            "pagina": pagina,
            "tamanio": tamanio,
            "total_registros": 0,
            "total_paginas": 0,
            "total_no_leidas": 0,
        }


def _token(**claims: object) -> str:
    return jwt.encode(claims, "clave-de-prueba-suficientemente-larga", algorithm="HS256")


async def test_get_notificaciones_requires_authorization_header() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/notificaciones")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


async def test_get_notificaciones_ignores_x_user_email_and_roles_headers() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/inspeccion/notificaciones",
                headers={"X-User-Email": "inspector@example.com", "X-User-Roles": "INSPECTOR"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


async def test_get_notificaciones_rejects_malformed_token() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/inspeccion/notificaciones",
                headers={"Authorization": "Bearer esto-no-es-un-jwt"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


async def test_get_notificaciones_extracts_email_and_roles_from_token() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    token = _token(preferred_username="david@example.com", roles=["INSPECTOR"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/inspeccion/notificaciones", headers={"Authorization": f"Bearer {token}"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert service.listar_args["email"] == "david@example.com"
    assert service.listar_args["roles"] == ["INSPECTOR"]


async def test_get_notificaciones_accepts_expired_token() -> None:
    """No se valida exp: la responsabilidad de rechazar tokens vencidos es del Gateway."""
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    hace_un_mes = int(time.time()) - 30 * 24 * 3600
    token = _token(preferred_username="david@example.com", roles=["INSPECTOR"], exp=hace_un_mes)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/inspeccion/notificaciones", headers={"Authorization": f"Bearer {token}"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert service.listar_args["email"] == "david@example.com"


async def test_get_notificaciones_rejects_token_without_preferred_username() -> None:
    service = FakeNotificacionService()
    app.dependency_overrides[get_notificacion_service] = lambda: service
    token = _token(roles=["INSPECTOR"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/inspeccion/notificaciones", headers={"Authorization": f"Bearer {token}"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
