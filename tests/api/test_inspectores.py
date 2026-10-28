from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.infrastructure.config.settings import Settings
from app.main import app
from app.presentation.api.dependencies.inspecciones import (
    get_azure_ad_client,
    get_current_user_email,
)


class FakeAzureAdClient:
    def __init__(self, members: list[dict[str, Any]]) -> None:
        self.members = members
        self.closed = False

    async def get_inspectores(self) -> list[dict[str, Any]]:
        return self.members

    async def aclose(self) -> None:
        self.closed = True


async def test_inspectores_endpoint_contract_and_openapi_registration() -> None:
    fake_client = FakeAzureAdClient(
        [
            {
                "id": "user-1",
                "displayName": "Ana López",
                "userPrincipalName": "ana@example.com",
                "mail": None,
            }
        ]
    )
    app.dependency_overrides[get_azure_ad_client] = lambda: fake_client
    app.dependency_overrides[get_current_user_email] = lambda: "caller@example.com"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/inspectores")
            openapi = (await client.get("/openapi.json")).json()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "inspectores": [
            {
                "displayName": "Ana López",
                "mail": "ana@example.com",
            }
        ],
    }
    assert "/v1/inspeccion/inspectores" in openapi["paths"]
    assert fake_client.closed is True


async def test_inspectores_endpoint_preserves_graph_mail_when_available() -> None:
    fake_client = FakeAzureAdClient(
        [
            {
                "id": "user-1",
                "displayName": "Ana López",
                "userPrincipalName": "ana@tenant.onmicrosoft.com",
                "mail": "ana@example.com",
            }
        ]
    )
    app.dependency_overrides[get_azure_ad_client] = lambda: fake_client
    app.dependency_overrides[get_current_user_email] = lambda: "caller@example.com"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/inspeccion/inspectores")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["inspectores"][0]["mail"] == "ana@example.com"


def test_incoming_auth_requires_email_outside_local_environment() -> None:
    settings = Settings(_env_file=None, is_local=False)  # type: ignore[call-arg]

    with pytest.raises(HTTPException) as captured:
        get_current_user_email(settings=settings, x_user_email=None)

    assert captured.value.status_code == 401


def test_incoming_auth_uses_local_identity_in_local_environment() -> None:
    settings = Settings(_env_file=None, is_local=True)  # type: ignore[call-arg]

    assert get_current_user_email(settings=settings, x_user_email=None) == "local@dev.test"
