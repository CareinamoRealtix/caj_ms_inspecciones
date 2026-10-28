from typing import Literal

from pydantic import BaseModel, Field


class OrigenIn(BaseModel):
    latitud: float = Field(ge=-90, le=90)
    longitud: float = Field(ge=-180, le=180)
    # Precisión del GPS en metros: informativa, no se usa en el cálculo.
    precision_m: float | None = Field(default=None, ge=0)


class SincronizacionSolicitudIn(BaseModel):
    """Body opcional de POST /sincronizacion: posición desde la que se sincroniza."""

    origen: OrigenIn | None = None


class SincronizacionJobCreadoResponse(BaseModel):
    job_id: str
    estado: Literal["pendiente"] = "pendiente"


class SincronizacionJobEstadoResponse(BaseModel):
    job_id: str
    estado: Literal["pendiente", "procesando", "listo", "error"]
    # Solo presente cuando estado == "listo": URL firmada de CloudFront de corta duración.
    url_firmada: str | None = None
    # Solo presente cuando estado == "error".
    error: str | None = None
