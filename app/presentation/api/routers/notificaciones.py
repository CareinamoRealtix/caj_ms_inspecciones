"""Router del módulo de notificaciones."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.notificacion_service import (
    NotificacionAjenaError,
    NotificacionNoActivaError,
    NotificacionNotFoundError,
    NotificacionService,
)
from app.presentation.api.dependencies.inspecciones import (
    UsuarioNotificacion,
    get_notificacion_service,
    get_notificacion_user,
)
from app.presentation.api.schemas.notificaciones import (
    AccionNotificacion,
    CrearNotificacionRequest,
    CrearNotificacionResponse,
    EstadoNotificacion,
    NotificacionListResponse,
)

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones"])


@router.get("", response_model=NotificacionListResponse)
async def get_notificaciones(
    svc: Annotated[NotificacionService, Depends(get_notificacion_service)],
    usuario: Annotated[UsuarioNotificacion, Depends(get_notificacion_user)],
    pagina: int = Query(default=1, ge=1),
    tamanio: int = Query(default=15, ge=1, le=100),
    estado: EstadoNotificacion | None = Query(default=None),
) -> NotificacionListResponse:
    """Lista las notificaciones del usuario autenticado, por su email o por su(s) rol(es)."""
    return await svc.listar(usuario.email, usuario.roles, estado, pagina, tamanio)


@router.patch("/{id_notificacion}")
async def marcar_notificacion(
    id_notificacion: uuid.UUID,
    accion: AccionNotificacion,
    svc: Annotated[NotificacionService, Depends(get_notificacion_service)],
    usuario: Annotated[UsuarioNotificacion, Depends(get_notificacion_user)],
) -> dict[str, str]:
    """Marca una notificación propia (por email o por rol) como vista o silenciada."""
    try:
        await svc.marcar(id_notificacion, accion, usuario.email, usuario.roles)
    except NotificacionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notificación no encontrada"
        ) from exc
    except NotificacionAjenaError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La notificación no pertenece al usuario autenticado",
        ) from exc
    except NotificacionNoActivaError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La notificación ya no está activa",
        ) from exc
    return {"estado": accion.value}


@router.post("", response_model=CrearNotificacionResponse, status_code=status.HTTP_201_CREATED)
async def crear_notificacion(
    body: CrearNotificacionRequest,
    svc: Annotated[NotificacionService, Depends(get_notificacion_service)],
    usuario: Annotated[UsuarioNotificacion, Depends(get_notificacion_user)],
) -> CrearNotificacionResponse:
    """Crea una notificación dirigida a un rol o a un email puntual.

    Ya no resuelve miembros de rol contra Microsoft Graph: una notificación de rol
    se guarda como una sola fila y se resuelve contra el rol de cada lector en
    GET /notificaciones.
    """
    return await svc.crear(body, creado_por=usuario.email)
