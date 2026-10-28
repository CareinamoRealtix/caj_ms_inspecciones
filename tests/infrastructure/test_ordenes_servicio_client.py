from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.infrastructure.clients.ordenes_servicio_client import (
    OrdenesServicioClient,
    OrdenesServicioWebhookError,
)
from app.infrastructure.config.settings import Settings


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ordenes_servicio_webhook_url": "http://ordenes.example.com/webhook-inspecciones",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _client(handler: Any, *, settings: Settings | None = None) -> OrdenesServicioClient:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OrdenesServicioClient(settings or _settings(), http_client=http_client)


async def test_posts_payload_to_configured_url() -> None:
    llamadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = _client(handler)

    await client.notificar_servicios_requeridos({"inspeccion_id": "abc"})

    assert len(llamadas) == 1
    assert str(llamadas[0].url) == "http://ordenes.example.com/webhook-inspecciones"
    assert llamadas[0].method == "POST"


async def test_disabled_when_url_is_empty_and_does_not_call_transport() -> None:
    llamadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        return httpx.Response(200, request=request)

    client = _client(handler, settings=_settings(ordenes_servicio_webhook_url=""))

    assert client.habilitado is False
    await client.notificar_servicios_requeridos({"inspeccion_id": "abc"})

    assert llamadas == []


async def test_non_2xx_status_raises_webhook_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    client = _client(handler)

    with pytest.raises(OrdenesServicioWebhookError):
        await client.notificar_servicios_requeridos({"inspeccion_id": "abc"})


async def test_network_error_raises_webhook_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)

    with pytest.raises(OrdenesServicioWebhookError):
        await client.notificar_servicios_requeridos({"inspeccion_id": "abc"})


async def test_logs_request_payload_and_ok_response(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"recibido": True}, request=request)

    client = _client(handler)

    with caplog.at_level("INFO"):
        await client.notificar_servicios_requeridos({"inspeccion_id": "abc"})

    solicitud = next(
        r
        for r in caplog.records
        if getattr(r, "event", None) == "ordenes_servicio_webhook_solicitud"
    )
    assert solicitud.payload == {"inspeccion_id": "abc"}
    assert solicitud.url == "http://ordenes.example.com/webhook-inspecciones"

    respuesta = next(
        r
        for r in caplog.records
        if getattr(r, "event", None) == "ordenes_servicio_webhook_respuesta_ok"
    )
    assert respuesta.status == 200
    assert "recibido" in respuesta.response_body


async def test_logs_error_response_body_and_status(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "campo inválido"}, request=request)

    client = _client(handler)

    with caplog.at_level("INFO"), pytest.raises(OrdenesServicioWebhookError):
        await client.notificar_servicios_requeridos({"inspeccion_id": "abc"})

    error = next(
        r
        for r in caplog.records
        if getattr(r, "event", None) == "ordenes_servicio_webhook_respuesta_error"
    )
    assert error.status == 422
    assert "campo inválido" in error.response_body
