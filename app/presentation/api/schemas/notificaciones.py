"""Contratos públicos del módulo de notificaciones."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator


class RolNotificacion(StrEnum):
    # inspecciones.rol_notificacion_enum (migración 20260922_0047) valida estos mismos
    # valores en base de datos. Agregar un rol acá requiere una migración adicional
    # (ALTER DOMAIN ... ADD CONSTRAINT) o la base rechazará el rol nuevo.
    INSPECTOR = "INSPECTOR"
    OFICIAL_BIENES_ADQUIRIDOS = "OFICIAL_BIENES_ADQUIRIDOS"


class EstadoNotificacion(StrEnum):
    # Estado de silenciado del lector, no de la notificación (CERRADA vive en
    # notificacion.estado_notificacion). Si fue vista o no se expresa aparte,
    # en NotificacionItem.fue_vista: ambos estados son independientes entre sí.
    NO_LEIDA = "NO_LEIDA"
    SILENCIADA = "SILENCIADA"


class AccionNotificacion(StrEnum):
    VISTA = "vista"
    SILENCIADA = "silenciada"


class NotificacionItem(BaseModel):
    id_notificacion: uuid.UUID
    tipo_notificacion: str
    titulo: str
    mensaje: str
    referencia_tipo: str | None
    referencia_id: uuid.UUID | None
    estado: EstadoNotificacion
    fue_vista: bool
    icono: str
    path: str | None
    modal: bool
    creador: str | None
    fecha_creacion: datetime
    fecha_vista: datetime | None


class NotificacionListResponse(BaseModel):
    data: list[NotificacionItem]
    pagina: int
    tamanio: int
    total_registros: int
    total_paginas: int
    total_no_leidas: int


class CrearNotificacionRequest(BaseModel):
    rol: RolNotificacion | None = None
    email_destinatario: str | None = None
    tipo_notificacion: str
    titulo: str
    mensaje: str
    referencia_tipo: str | None = None
    referencia_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validar_destinatario_unico(self) -> CrearNotificacionRequest:
        if bool(self.rol) == bool(self.email_destinatario):
            raise ValueError(
                "Debe indicar exactamente uno de: rol o email_destinatario"
            )
        return self


class CrearNotificacionResponse(BaseModel):
    id_notificacion: uuid.UUID
