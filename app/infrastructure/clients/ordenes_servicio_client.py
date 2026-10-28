"""Cliente para el webhook de ms-requerimientos (órdenes de servicio)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)


class OrdenesServicioWebhookError(Exception):
    """La llamada al webhook de ms-requerimientos falló (red, timeout o status != 2xx)."""


class OrdenesServicioClient:
    """Notifica a ms-requerimientos los servicios requeridos de un levantamiento finalizado."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._webhook_url = settings.ordenes_servicio_webhook_url
        self._client = http_client or httpx.AsyncClient(
            timeout=settings.ordenes_servicio_webhook_timeout
        )
        self._owns_http_client = http_client is None

    @property
    def habilitado(self) -> bool:
        return bool(self._webhook_url.strip())

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._client.aclose()

    async def notificar_servicios_requeridos(self, payload: dict[str, Any]) -> None:
        if not self.habilitado:
            logger.info(
                "Webhook de ms-requerimientos deshabilitado (ORDENES_SERVICIO_WEBHOOK_URL "
                "vacío); se omite el envío",
                extra={"event": "ordenes_servicio_webhook_deshabilitado"},
            )
            return

        logger.info(
            "Llamando al webhook de ms-requerimientos",
            extra={
                "event": "ordenes_servicio_webhook_solicitud",
                "url": self._webhook_url,
                "payload": payload,
            },
        )

        try:
            response = await self._client.post(self._webhook_url, json=payload)
            response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            status_code = (
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            )
            response_body = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else None
            logger.warning(
                "El webhook de ms-requerimientos respondió con error",
                extra={
                    "event": "ordenes_servicio_webhook_respuesta_error",
                    "status": status_code,
                    "response_body": response_body,
                },
            )
            raise OrdenesServicioWebhookError(
                f"Falló la llamada al webhook de ms-requerimientos (status={status_code})"
            ) from exc

        logger.info(
            "El webhook de ms-requerimientos respondió correctamente",
            extra={
                "event": "ordenes_servicio_webhook_respuesta_ok",
                "status": response.status_code,
                "response_body": response.text,
            },
        )
