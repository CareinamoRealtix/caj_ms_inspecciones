"""Endpoints de jobs internos (disparadores automáticos de HU.5)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.alertas_vencimiento_service import AlertasVencimientoService
from app.presentation.api.dependencies.inspecciones import (
    get_alertas_vencimiento_service,
    get_current_user_email,
)
from app.presentation.api.schemas.jobs import AlertasVencimientoResponse

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/alertas-vencimiento", response_model=AlertasVencimientoResponse)
async def ejecutar_alertas_vencimiento(
    svc: Annotated[AlertasVencimientoService, Depends(get_alertas_vencimiento_service)],
    usuario: Annotated[str | None, Depends(get_current_user_email)],
) -> AlertasVencimientoResponse:
    """Emite la notificación de "próxima a vencer" al inspector asignado de cada finca.

    Evalúa las mismas fincas que la pantalla de Control de inspecciones marca con
    Estado de Alerta "Próxima a vencer". Pensado para ser invocado una vez al día
    por un scheduler (EventBridge, 8:00am). Como una misma finca puede seguir
    "próxima a vencer" varios días seguidos, cada corrida crea una notificación
    nueva (queda como historial de las alertas emitidas para esa finca) y silencia
    —sin cerrar— la más reciente que hubiera quedado activa, para que solo la de
    hoy aparezca sin leer. Cuando una finca deja de estar "próxima" para pasar a
    "vencida", la última notificación de "próxima a vencer" que quedó activa se
    marca como vista y silenciada, porque esa alerta ya dejó de aplicar.
    """
    resultado = await svc.emitir(creado_por=usuario)
    return AlertasVencimientoResponse(
        fincas_evaluadas=resultado.fincas_evaluadas,
        notificaciones_creadas=resultado.notificaciones_creadas,
        notificaciones_silenciadas=resultado.notificaciones_silenciadas,
        fincas_omitidas_sin_inspector=resultado.fincas_omitidas_sin_inspector,
    )
