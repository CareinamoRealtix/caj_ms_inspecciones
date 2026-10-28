"""Dependencias FastAPI para el módulo de inspecciones."""

from dataclasses import dataclass, field
from typing import Annotated

import asyncpg
from fastapi import Depends, Header, HTTPException, status

from app.application.alertas_vencimiento_service import AlertasVencimientoService
from app.application.inspeccion_service import InspeccionService
from app.application.notificacion_service import NotificacionService
from app.application.sincronizacion_service import SincronizacionService
from app.application.subida_service import SubidaService
from app.infrastructure.clients.aws_sincronizacion import (
    BatchSubmitter,
    CloudFrontUrlSigner,
)
from app.infrastructure.clients.aws_subida import SubidaS3
from app.infrastructure.clients.azure_ad_client import AzureAdClient
from app.infrastructure.clients.entra_token_decoder import TokenDecodeError, decode_entra_token
from app.infrastructure.clients.ordenes_servicio_client import OrdenesServicioClient
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.database.inspeccion_repository import InspeccionRepository
from app.infrastructure.database.notificacion_repository import NotificacionRepository
from app.infrastructure.database.sincronizacion_estado_repository import JobStore, SubidaStore
from app.presentation.api.dependencies.pool import get_pool


def get_inspeccion_service(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],  # type: ignore[type-arg]
    settings: Annotated[Settings, Depends(get_settings)],
) -> InspeccionService:
    repo = InspeccionRepository(pool)
    return InspeccionService(
        repo, OrdenesServicioClient(settings), fotos_signer=CloudFrontUrlSigner(settings)
    )


def get_notificacion_service(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],  # type: ignore[type-arg]
) -> NotificacionService:
    repo = NotificacionRepository(pool)
    return NotificacionService(repo)


def get_alertas_vencimiento_service(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],  # type: ignore[type-arg]
) -> AlertasVencimientoService:
    return AlertasVencimientoService(
        InspeccionService(InspeccionRepository(pool)),
        NotificacionService(NotificacionRepository(pool)),
    )


def get_sincronizacion_service(
    settings: Annotated[Settings, Depends(get_settings)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],  # type: ignore[type-arg]
) -> SincronizacionService:
    # Los clientes boto3 se crean al primer uso: con la sincronización deshabilitada no se toca AWS.
    return SincronizacionService(
        settings, JobStore(pool, settings), BatchSubmitter(settings), CloudFrontUrlSigner(settings)
    )


def get_subida_service(
    settings: Annotated[Settings, Depends(get_settings)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],  # type: ignore[type-arg]
) -> SubidaService:
    return SubidaService(
        settings, SubidaStore(pool, settings), SubidaS3(settings), BatchSubmitter(settings)
    )


def get_azure_ad_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AzureAdClient:
    return AzureAdClient(settings)


def get_current_user_email(
    settings: Annotated[Settings, Depends(get_settings)],
    x_user_email: str | None = Header(default=None),
) -> str:
    if settings.is_local:
        return x_user_email or "local@dev.test"
    if not x_user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El header X-User-Email es requerido",
        )
    return x_user_email


def require_direct_levantamiento_habilitado(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.enable_direct_levantamiento_endpoint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@dataclass
class UsuarioNotificacion:
    """Identidad resuelta del usuario autenticado: email y rol(es) para notificaciones."""

    email: str
    roles: list[str] = field(default_factory=list)


def get_notificacion_user(
    authorization: str | None = Header(default=None),
) -> UsuarioNotificacion:
    """Extrae email y rol(es) del usuario desde el `Authorization: Bearer` del Gateway.

    No valida firma, expiración, `aud` ni `iss`: esa responsabilidad queda del lado
    del API Gateway. Este microservicio solo confía en el contenido del token y
    extrae `preferred_username` (correo) y `roles`.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El header Authorization Bearer es requerido",
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_entra_token(token)
    except TokenDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    email = claims.get("preferred_username")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token no incluye preferred_username",
        )
    roles = claims.get("roles") or []
    return UsuarioNotificacion(email=email, roles=list(roles))
