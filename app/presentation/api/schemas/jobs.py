"""Contratos de los endpoints de jobs (disparadores automáticos de HU.5)."""
from __future__ import annotations

from pydantic import BaseModel


class AlertasVencimientoResponse(BaseModel):
    fincas_evaluadas: int
    notificaciones_creadas: int
    notificaciones_silenciadas: int
    fincas_omitidas_sin_inspector: int
