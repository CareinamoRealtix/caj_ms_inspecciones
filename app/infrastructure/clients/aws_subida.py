"""Clientes AWS de la subida de levantamientos por ZIP (HU.12, Etapa 2).

Mismo criterio que `aws_sincronizacion`: boto3 es síncrono (se ejecuta en un hilo) y los clientes
se crean al usarse, así que arrancar sin la infraestructura desplegada no falla.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.infrastructure.clients.aws_sincronizacion import SincronizacionNoDisponibleError
from app.infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)

ESTADO_PENDIENTE_CARGA = "pendiente_carga"
ESTADO_PENDIENTE = "pendiente"
ESTADO_PROCESANDO = "procesando"
ESTADO_LISTO = "listo"
ESTADO_PARCIAL = "parcial"
ESTADO_ERROR = "error"
ESTADOS_TERMINALES = frozenset({ESTADO_LISTO, ESTADO_PARCIAL, ESTADO_ERROR})


@dataclass(frozen=True)
class SubidaJob:
    subida_id: str
    email_inspector: str
    estado: str
    s3_key: str
    tamano_bytes: int
    sha256: str
    cantidad_levantamientos: int
    resultados: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    batch_job_id: str | None = None


class SubidaS3:
    """Acceso a S3 de la subida: URL de carga prefirmada, verificación y escritura de imágenes."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _s3(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "s3",
                region_name=self._settings.aws_region,
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def _bucket_subidas(self) -> str:
        if not self._settings.subida_s3_bucket:
            raise SincronizacionNoDisponibleError("Falta SUBIDA_S3_BUCKET")
        return self._settings.subida_s3_bucket

    def _bucket_fotos(self) -> str:
        if not self._settings.fotos_s3_bucket:
            raise SincronizacionNoDisponibleError("Falta FOTOS_S3_BUCKET")
        return self._settings.fotos_s3_bucket

    async def url_carga(self, s3_key: str, tamano_bytes: int) -> str:
        """URL prefirmada de `PUT`, atada a la key y al tamaño exacto que declaró la app."""
        return await asyncio.to_thread(
            self._s3().generate_presigned_url,
            "put_object",
            Params={
                "Bucket": self._bucket_subidas(),
                "Key": s3_key,
                "ContentType": "application/zip",
                "ContentLength": tamano_bytes,
            },
            ExpiresIn=self._settings.subida_url_ttl_segundos,
        )

    async def tamano_zip(self, s3_key: str) -> int | None:
        """Tamaño del ZIP subido, o None si todavía no existe.

        Sin `s3:ListBucket`, S3 responde 403 (no 404) cuando la key no existe, para no revelar qué
        objetos hay; el rol de la API no tiene ese permiso a propósito. Por eso un 403 se trata
        igual que «no está»: la app recibe un 409 y vuelve a subir el archivo.
        """
        try:
            respuesta = await asyncio.to_thread(
                self._s3().head_object, Bucket=self._bucket_subidas(), Key=s3_key
            )
        except ClientError as exc:
            codigo = exc.response["Error"]["Code"]
            if codigo in ("404", "NoSuchKey", "NotFound", "403", "Forbidden", "AccessDenied"):
                if codigo not in ("404", "NoSuchKey", "NotFound"):
                    logger.warning(
                        "HeadObject denegado: el ZIP no existe o falta permiso de lectura",
                        extra={"event": "subida_head_denegado", "codigo": codigo, "s3_key": s3_key},
                    )
                return None
            raise
        return int(respuesta["ContentLength"])

    async def descargar_zip(self, s3_key: str, destino: BinaryIO) -> None:
        await asyncio.to_thread(
            self._s3().download_fileobj, self._bucket_subidas(), s3_key, destino
        )

    async def subir_imagen(self, s3_key: str, contenido: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._s3().put_object,
            Bucket=self._bucket_fotos(),
            Key=s3_key,
            Body=contenido,
            ContentType=content_type,
        )
