"""Router de inspectores — consulta Microsoft Entra ID."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.application.inspectores import build_inspector_items
from app.infrastructure.clients.azure_ad_client import AzureAdClient, AzureAdError
from app.presentation.api.dependencies.inspecciones import get_azure_ad_client
from app.presentation.api.schemas.inspectores import InspectoresResponse

router = APIRouter(prefix="/inspectores", tags=["Inspectores"])
logger = logging.getLogger(__name__)


@router.get("", response_model=InspectoresResponse)
async def get_inspectores(
    client: Annotated[AzureAdClient, Depends(get_azure_ad_client)],
) -> InspectoresResponse:
    """Devuelve los miembros del grupo Inspectores en Microsoft Entra ID."""
    try:
        members = await client.get_inspectores()
    except AzureAdError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected inspectors endpoint error",
            extra={"event": "inspectors_unexpected_error"},
        )
        raise HTTPException(status_code=500, detail="Error interno del servidor") from exc
    finally:
        await client.aclose()

    inspectores = build_inspector_items(members)
    return InspectoresResponse(total=len(inspectores), inspectores=inspectores)
