"""Sincronización offline asíncrona (HU.12): dispara el job de Batch y consulta su estado."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.application.sincronizacion_service import JobNoEncontradoError, SincronizacionService
from app.infrastructure.clients.aws_sincronizacion import (
    EncolarJobError,
    SincronizacionNoDisponibleError,
)
from app.presentation.api.dependencies.inspecciones import (
    get_current_user_email,
    get_sincronizacion_service,
)
from app.presentation.api.schemas.sincronizacion_job import (
    SincronizacionJobCreadoResponse,
    SincronizacionJobEstadoResponse,
    SincronizacionSolicitudIn,
)

router = APIRouter(prefix="/sincronizacion", tags=["Sincronización"])

NO_DISPONIBLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="La sincronización no está disponible en este entorno",
)


@router.post(
    "",
    response_model=SincronizacionJobCreadoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def iniciar_sincronizacion(
    svc: Annotated[SincronizacionService, Depends(get_sincronizacion_service)],
    usuario: Annotated[str, Depends(get_current_user_email)],
    solicitud: Annotated[SincronizacionSolicitudIn | None, Body()] = None,
) -> SincronizacionJobCreadoResponse:
    """Dispara la generación del paquete de sincronización del inspector autenticado.

    Con `origen` en el body, el paquete incluye una ruta óptima por fecha desde ese punto.
    """
    origen = (
        (solicitud.origen.latitud, solicitud.origen.longitud)
        if solicitud is not None and solicitud.origen is not None
        else None
    )
    try:
        job_id = await svc.iniciar(usuario, origen)
    except SincronizacionNoDisponibleError as exc:
        raise NO_DISPONIBLE from exc
    except EncolarJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo iniciar la sincronización, intente nuevamente",
        ) from exc
    return SincronizacionJobCreadoResponse(job_id=job_id)


@router.get("/{job_id}", response_model=SincronizacionJobEstadoResponse)
async def consultar_sincronizacion(
    job_id: str,
    svc: Annotated[SincronizacionService, Depends(get_sincronizacion_service)],
    usuario: Annotated[str, Depends(get_current_user_email)],
    espera: Annotated[int, Query(ge=0, le=50, description="Segundos máximos de espera")] = 25,
) -> SincronizacionJobEstadoResponse:
    """Long polling: responde en cuanto el job termina o al agotarse la ventana de espera.

    Si devuelve `procesando`/`pendiente`, la app vuelve a llamar de inmediato. Con `listo`
    incluye `url_firmada` (CloudFront, corta duración) para descargar el .zip.
    """
    try:
        estado = await svc.consultar(job_id, usuario, espera)
    except SincronizacionNoDisponibleError as exc:
        raise NO_DISPONIBLE from exc
    except JobNoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job no encontrado"
        ) from exc
    return SincronizacionJobEstadoResponse(
        job_id=estado.job_id,
        estado=estado.estado,  # type: ignore[arg-type]
        url_firmada=estado.url_firmada,
        error=estado.error,
    )
