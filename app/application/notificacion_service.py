"""Lógica de negocio del módulo de notificaciones."""
from __future__ import annotations

import math
import uuid

from app.infrastructure.database.notificacion_repository import NotificacionRepository
from app.presentation.api.schemas.notificaciones import (
    AccionNotificacion,
    CrearNotificacionRequest,
    CrearNotificacionResponse,
    EstadoNotificacion,
    NotificacionItem,
    NotificacionListResponse,
)


class NotificacionNotFoundError(Exception):
    """La notificación solicitada no existe."""


class NotificacionAjenaError(Exception):
    """La notificación no aplica al usuario autenticado, ni por email ni por rol."""


class NotificacionNoActivaError(Exception):
    """La notificación ya fue cerrada y no admite esta acción."""


class NotificacionService:
    def __init__(self, repo: NotificacionRepository) -> None:
        self._repo = repo

    async def listar(
        self,
        email: str,
        roles: list[str],
        estado: EstadoNotificacion | None,
        pagina: int,
        tamanio: int,
    ) -> NotificacionListResponse:
        estados = [estado.value] if estado else None
        rows, total = await self._repo.list_for_user(email, roles, estados, pagina, tamanio)
        total_no_leidas = await self._repo.count_no_leidas(email, roles)
        return NotificacionListResponse(
            data=[NotificacionItem(**dict(row)) for row in rows],
            pagina=pagina,
            tamanio=tamanio,
            total_registros=total,
            total_paginas=math.ceil(total / tamanio) if total else 0,
            total_no_leidas=total_no_leidas,
        )

    async def marcar(
        self,
        id_notificacion: uuid.UUID,
        accion: AccionNotificacion,
        email: str,
        roles: list[str],
    ) -> None:
        row = await self._repo.get_by_id(id_notificacion)
        if row is None:
            raise NotificacionNotFoundError(id_notificacion)

        aplica_por_email = row["email_destinatario"] == email
        aplica_por_rol = row["rol_destino"] is not None and row["rol_destino"] in roles
        if not (aplica_por_email or aplica_por_rol):
            raise NotificacionAjenaError(id_notificacion)
        if row["estado_notificacion"] == "CERRADA":
            raise NotificacionNoActivaError(id_notificacion)

        if accion is AccionNotificacion.VISTA:
            await self._repo.marcar_vista(id_notificacion, email)
        else:
            await self._repo.marcar_silenciada(id_notificacion, email)

    async def crear(
        self,
        body: CrearNotificacionRequest,
        creado_por: str | None,
    ) -> CrearNotificacionResponse:
        if body.referencia_tipo is not None and body.referencia_id is not None:
            await self._repo.close_previous(
                body.rol.value if body.rol else None,
                body.email_destinatario,
                body.referencia_tipo,
                body.referencia_id,
                body.tipo_notificacion,
            )
        return await self._insertar(body, creado_por)

    async def crear_sin_cerrar_previas(
        self,
        body: CrearNotificacionRequest,
        creado_por: str | None,
    ) -> CrearNotificacionResponse:
        """Como `crear`, pero sin cerrar notificaciones previas de la misma referencia.

        Para flujos donde tener varias notificaciones activas de una misma referencia
        es intencional: el job de alertas de vencimiento crea una por día mientras la
        finca esté "próxima a vencer", para que quede como historial/log, en vez de
        editar o cerrar la de ayer.
        """
        return await self._insertar(body, creado_por)

    async def _insertar(
        self, body: CrearNotificacionRequest, creado_por: str | None
    ) -> CrearNotificacionResponse:
        row = await self._repo.insert(
            {
                "rol_destino": body.rol.value if body.rol else None,
                "email_destinatario": body.email_destinatario,
                "tipo_notificacion": body.tipo_notificacion,
                "titulo": body.titulo,
                "mensaje": body.mensaje,
                "referencia_tipo": body.referencia_tipo,
                "referencia_id": body.referencia_id,
                "creado_por": creado_por,
            }
        )
        return CrearNotificacionResponse(id_notificacion=row["id_notificacion"])

    # ------------------------------------------------------------------
    # Uso interno de jobs recurrentes (alertas de vencimiento, etc.)
    # ------------------------------------------------------------------

    async def get_ultima_activa_por_referencia(
        self,
        email_destinatario: str,
        referencia_tipo: str,
        referencia_id: uuid.UUID,
        tipo_notificacion: str,
    ) -> uuid.UUID | None:
        return await self._repo.get_ultima_activa_por_referencia(
            email_destinatario, referencia_tipo, referencia_id, tipo_notificacion
        )

    async def marcar_silenciada_interno(self, id_notificacion: uuid.UUID, email: str) -> None:
        await self._repo.marcar_silenciada(id_notificacion, email)

    async def marcar_vista_y_silenciada(self, id_notificacion: uuid.UUID, email: str) -> None:
        await self._repo.marcar_vista_y_silenciada(id_notificacion, email)
