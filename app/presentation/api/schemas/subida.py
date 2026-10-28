from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EstadoSubida = Literal["pendiente_carga", "pendiente", "procesando", "listo", "parcial", "error"]


class SubidaCrearRequest(BaseModel):
    tamano_bytes: int = Field(gt=0)
    # SHA-256 del .zip en hexadecimal; el job lo verifica contra lo que realmente descargó.
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    cantidad_levantamientos: int = Field(ge=1)


class SubidaCreadaResponse(BaseModel):
    subida_id: str
    url_carga: str
    vence_en: datetime


class SubidaResultadoItem(BaseModel):
    id_inspeccion: str
    exito: bool
    repetido: bool = False
    id_levantamiento: str | None = None
    codigo_error: str | None = None
    mensaje: str | None = None


class SubidaEstadoResponse(BaseModel):
    subida_id: str
    estado: EstadoSubida
    # Presente cuando el job ya empezó a procesar; la app marca como enviadas las `exito`.
    resultados: list[SubidaResultadoItem] = Field(default_factory=list)
    # Solo cuando estado == "error".
    error: str | None = None
