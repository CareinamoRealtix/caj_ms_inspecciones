"""Cliente para Microsoft Graph / Microsoft Entra ID."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import msal

from app.infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]


class AzureAdError(Exception):
    """Error controlado al consultar Microsoft Entra ID."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AzureAdClient:
    """Autentica la aplicación y consulta usuarios del grupo Inspectores."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        msal_app: Any | None = None,
    ) -> None:
        self._tenant_id = settings.azure_tenant_id
        self._client_id = settings.azure_backend_client_id
        self._client_secret = settings.azure_backend_client_secret
        self._client = http_client or httpx.AsyncClient(timeout=15.0)
        self._owns_http_client = http_client is None
        self._msal_app = msal_app

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._client.aclose()

    def _validate_configuration(self) -> None:
        values = {
            "AZURE_TENANT_ID": self._tenant_id,
            "AZURE_BACKEND_CLIENT_ID": self._client_id,
            "AZURE_BACKEND_CLIENT_SECRET": self._client_secret,
        }
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise AzureAdError(
                status_code=500,
                detail=f"Configuración Azure incompleta. Faltan variables: {', '.join(missing)}.",
            )

    async def _get_token(self) -> str:
        self._validate_configuration()
        application = self._msal_app or msal.ConfidentialClientApplication(
            client_id=self._client_id,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            client_credential=self._client_secret,
        )
        result = await asyncio.to_thread(application.acquire_token_for_client, scopes=_SCOPES)
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise AzureAdError(
                status_code=502,
                detail=(
                    "No se pudo autenticar con Microsoft Entra ID. "
                    "Revisa las credenciales configuradas."
                ),
            )
        return token

    async def _find_group_id(self, group_name: str, headers: dict[str, str]) -> str:
        try:
            response = await self._client.get(
                f"{_GRAPH_BASE}/groups",
                params={
                    "$filter": f"displayName eq '{group_name}'",
                    "$select": "id,displayName",
                },
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            status_code = (
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            )
            logger.warning(
                "Microsoft Graph group lookup failed",
                extra={"event": "graph_group_lookup_failed", "graph_status": status_code},
            )
            raise AzureAdError(
                status_code=502,
                detail="Error al consultar Microsoft Graph al buscar el grupo.",
            ) from exc

        groups = payload.get("value", []) if isinstance(payload, dict) else []
        group_id = groups[0].get("id") if groups and isinstance(groups[0], dict) else None
        if not isinstance(group_id, str) or not group_id:
            raise AzureAdError(
                status_code=404,
                detail=f"El grupo '{group_name}' no existe en Microsoft Entra ID.",
            )
        return group_id

    async def _get_group_users(
        self, group_id: str, headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        url: str | None = (
            f"{_GRAPH_BASE}/groups/{group_id}/members/microsoft.graph.user"
        )
        params: dict[str, str] | None = {
            "$select": "id,displayName,userPrincipalName,mail"
        }
        members: list[dict[str, Any]] = []

        while url is not None:
            try:
                response = await self._client.get(url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                status_code = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                logger.warning(
                    "Microsoft Graph members lookup failed",
                    extra={
                        "event": "graph_members_lookup_failed",
                        "graph_status": status_code,
                    },
                )
                raise AzureAdError(
                    status_code=502,
                    detail="Error al obtener miembros del grupo desde Microsoft Graph.",
                ) from exc

            page = payload.get("value", []) if isinstance(payload, dict) else []
            members.extend(item for item in page if isinstance(item, dict))
            next_link = payload.get("@odata.nextLink") if isinstance(payload, dict) else None
            url = next_link if isinstance(next_link, str) and next_link else None
            params = None

        return members

    async def get_group_members(self, group_name: str) -> list[dict[str, Any]]:
        """Resuelve los usuarios miembros de un grupo de Microsoft Entra ID por su displayName."""
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        group_id = await self._find_group_id(group_name, headers)
        return await self._get_group_users(group_id, headers)

    async def get_inspectores(self) -> list[dict[str, Any]]:
        return await self.get_group_members("Inspectores")
