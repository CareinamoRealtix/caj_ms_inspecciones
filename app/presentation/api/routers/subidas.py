"""Subida de levantamientos por ZIP (HU.12, Etapa 2): carga prefirmada, confirmación y estado."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.subida_service import (
    SubidaCargaIncompletaError,
    SubidaFueraDeLimiteError,
    SubidaNoEncontradaError,
    SubidaService,
)
from app.infrastructure.clients.aws_sincronizacion import (
    EncolarJobError,
    SincronizacionNoDisponibleError,
)
from app.presentation.api.dependencies.inspecciones import (
    get_current_user_email,
    get_subida_service,
)
from app.presentation.api.schemas.subida import (
    SubidaCreadaResponse,
    SubidaCrearRequest,
    SubidaEstadoResponse,
)

router = APIRouter(prefix="/subidas", tags=["Subida de levantamientos"])

NO_DISPONIBLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="La subida no está disponible en este entorno",
)
NO_ENCONTRADA = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subida no encontrada")


@router.post("", response_model=SubidaCreadaResponse, status_code=status.HTTP_201_CREATED)
async def crear_subida(
    body: SubidaCrearRequest,
    svc: Annotated[SubidaService, Depends(get_subida_service)],
    usuario: Annotated[str, Depends(get_current_user_email)],
) -> SubidaCreadaResponse:
    """Registra la subida y devuelve la URL prefirmada (`PUT`) donde la app deja el .zip.

    El `PUT` debe enviar `Content-Type: application/zip` y un `Content-Length` igual a
    `tamano_bytes`; la URL vence en `vence_en`.
    """
    try:
        creada = await svc.iniciar(
            usuario, body.tamano_bytes, body.sha256, body.cantidad_levantamientos
        )
    except SincronizacionNoDisponibleError as exc:
        raise NO_DISPONIBLE from exc
    except SubidaFueraDeLimiteError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    return SubidaCreadaResponse(
        subida_id=creada.subida_id, url_carga=creada.url_carga, vence_en=creada.vence_en
    )


@router.post(
    "/{subida_id}/confirmar",
    response_model=SubidaEstadoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirmar_subida(
    subida_id: str,
    svc: Annotated[SubidaService, Depends(get_subida_service)],
    usuario: Annotated[str, Depends(get_current_user_email)],
) -> SubidaEstadoResponse:
    """Confirma que el .zip ya se subió y encola su procesamiento. Es idempotente."""
    try:
        estado = await svc.confirmar(subida_id, usuario)
    except SincronizacionNoDisponibleError as exc:
        raise NO_DISPONIBLE from exc
    except SubidaNoEncontradaError as exc:
        raise NO_ENCONTRADA from exc
    except SubidaCargaIncompletaError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El archivo no está en el servidor o su tamaño no coincide; vuelva a subirlo",
        ) from exc
    except EncolarJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo iniciar el procesamiento, intente nuevamente",
        ) from exc
    return SubidaEstadoResponse(subida_id=estado.subida_id, estado=estado.estado)  # type: ignore[arg-type]


@router.get("/{subida_id}", response_model=SubidaEstadoResponse)
async def consultar_subida(
    subida_id: str,
    svc: Annotated[SubidaService, Depends(get_subida_service)],
    usuario: Annotated[str, Depends(get_current_user_email)],
    espera: Annotated[int, Query(ge=0, le=50, description="Segundos máximos de espera")] = 25,
) -> SubidaEstadoResponse:
    """Long polling: responde al terminar el procesamiento o al agotarse la ventana de espera.

    Con `procesando`/`pendiente` la app vuelve a llamar de inmediato. Con `listo`, `parcial` o
    `error` trae el resultado por inspección en `resultados`.
    """
    try:
        estado = await svc.consultar(subida_id, usuario, espera)
    except SincronizacionNoDisponibleError as exc:
        raise NO_DISPONIBLE from exc
    except SubidaNoEncontradaError as exc:
        raise NO_ENCONTRADA from exc
    return SubidaEstadoResponse(
        subida_id=estado.subida_id,
        estado=estado.estado,  # type: ignore[arg-type]
        resultados=estado.resultados,  # type: ignore[arg-type]
        error=estado.error,
    )
