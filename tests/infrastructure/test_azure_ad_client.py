from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.infrastructure.clients.azure_ad_client import AzureAdClient, AzureAdError
from app.infrastructure.config.settings import Settings


class FakeMsalApplication:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.scopes: list[str] | None = None

    def acquire_token_for_client(self, *, scopes: list[str]) -> dict[str, Any]:
        self.scopes = scopes
        return self.result


def _settings(**overrides: str) -> Settings:
    values = {
        "azure_tenant_id": "tenant-id",
        "azure_backend_client_id": "client-id",
        "azure_backend_client_secret": "client-secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _client(
    handler: Any,
    *,
    settings: Settings | None = None,
    token_result: dict[str, Any] | None = None,
) -> tuple[AzureAdClient, httpx.AsyncClient, FakeMsalApplication]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=15.0)
    msal_app = FakeMsalApplication(token_result or {"access_token": "test-token"})
    client = AzureAdClient(
        settings or _settings(),
        http_client=http_client,
        msal_app=msal_app,
    )
    return client, http_client, msal_app


async def test_missing_all_azure_variables_returns_configuration_error() -> None:
    client, http_client, _ = _client(
        lambda request: httpx.Response(500, request=request),
        settings=_settings(
            azure_tenant_id="",
            azure_backend_client_id="",
            azure_backend_client_secret="",
        ),
    )
    try:
        with pytest.raises(AzureAdError) as captured:
            await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 500
    assert "AZURE_TENANT_ID" in captured.value.detail
    assert "AZURE_BACKEND_CLIENT_ID" in captured.value.detail
    assert "AZURE_BACKEND_CLIENT_SECRET" in captured.value.detail


async def test_missing_only_client_secret_returns_configuration_error() -> None:
    client, http_client, _ = _client(
        lambda request: httpx.Response(500, request=request),
        settings=_settings(azure_backend_client_secret=""),
    )
    try:
        with pytest.raises(AzureAdError) as captured:
            await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 500
    assert "AZURE_BACKEND_CLIENT_SECRET" in captured.value.detail
    assert "AZURE_TENANT_ID" not in captured.value.detail


async def test_msal_access_token_is_acquired_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_called = False

    async def fake_to_thread(function: Any, /, *args: Any, **kwargs: Any) -> Any:
        nonlocal thread_called
        thread_called = True
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.clients.azure_ad_client.asyncio.to_thread", fake_to_thread
    )
    client, http_client, msal_app = _client(
        lambda request: httpx.Response(500, request=request)
    )
    try:
        token = await client._get_token()
    finally:
        await http_client.aclose()

    assert token == "test-token"
    assert thread_called is True
    assert msal_app.scopes == ["https://graph.microsoft.com/.default"]


async def test_msal_error_without_access_token_returns_502() -> None:
    client, http_client, _ = _client(
        lambda request: httpx.Response(500, request=request),
        token_result={"error": "invalid_client"},
    )
    try:
        with pytest.raises(AzureAdError) as captured:
            await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 502
    assert captured.value.detail.startswith("No se pudo autenticar")


async def test_group_members_are_combined_from_all_pages() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1.0/groups":
            assert request.url.params["$filter"] == "displayName eq 'Inspectores'"
            assert request.url.params["$select"] == "id,displayName"
            return httpx.Response(200, json={"value": [{"id": "group-id"}]}, request=request)
        if request.url.path.endswith("/members/microsoft.graph.user"):
            assert request.url.params["$select"] == "id,displayName,userPrincipalName,mail"
            return httpx.Response(
                200,
                json={
                    "value": [{"id": "user-1", "displayName": "Ana"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page",
                },
                request=request,
            )
        assert request.url.path == "/v1.0/next-page"
        assert not request.url.params
        return httpx.Response(
            200,
            json={"value": [{"id": "user-2", "displayName": "Carlos"}]},
            request=request,
        )

    client, http_client, _ = _client(handler)
    try:
        members = await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert [member["id"] for member in members] == ["user-1", "user-2"]
    assert len(calls) == 3
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in calls)


async def test_missing_inspectors_group_returns_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": []}, request=request)

    client, http_client, _ = _client(handler)
    try:
        with pytest.raises(AzureAdError) as captured:
            await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 404
    assert captured.value.detail == "El grupo 'Inspectores' no existe en Microsoft Entra ID."


async def test_graph_group_lookup_failure_returns_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"}, request=request)

    client, http_client, _ = _client(handler)
    try:
        with pytest.raises(AzureAdError) as captured:
            await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 502
    assert captured.value.detail == "Error al consultar Microsoft Graph al buscar el grupo."


async def test_graph_members_lookup_failure_returns_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/groups":
            return httpx.Response(200, json={"value": [{"id": "group-id"}]}, request=request)
        return httpx.Response(503, json={"error": "unavailable"}, request=request)

    client, http_client, _ = _client(handler)
    try:
        with pytest.raises(AzureAdError) as captured:
            await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 502
    assert captured.value.detail == "Error al obtener miembros del grupo desde Microsoft Graph."


async def test_graph_next_page_failure_returns_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/groups":
            return httpx.Response(200, json={"value": [{"id": "group-id"}]}, request=request)
        if request.url.path.endswith("/members/microsoft.graph.user"):
            return httpx.Response(
                200,
                json={
                    "value": [{"id": "user-1"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page",
                },
                request=request,
            )
        return httpx.Response(500, json={"error": "pagination failed"}, request=request)

    client, http_client, _ = _client(handler)
    try:
        with pytest.raises(AzureAdError) as captured:
            await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert captured.value.status_code == 502
    assert captured.value.detail == "Error al obtener miembros del grupo desde Microsoft Graph."


async def test_group_without_users_returns_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/groups":
            return httpx.Response(200, json={"value": [{"id": "group-id"}]}, request=request)
        return httpx.Response(200, json={"value": []}, request=request)

    client, http_client, _ = _client(handler)
    try:
        members = await client.get_inspectores()
    finally:
        await http_client.aclose()

    assert members == []
