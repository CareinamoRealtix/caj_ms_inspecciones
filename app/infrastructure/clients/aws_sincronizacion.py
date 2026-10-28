"""Clientes AWS de la sincronización offline (HU.12): Batch, S3 y CloudFront.

El estado del job vive en la base (`database/sincronizacion_estado_repository.py`).

boto3 es síncrono; las llamadas se ejecutan en un hilo (`asyncio.to_thread`) para no bloquear
el event loop. Los clientes se crean de forma perezosa: importar este módulo o arrancar la
aplicación sin infraestructura AWS no falla.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import boto3
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.infrastructure.config.settings import Settings

ESTADO_PENDIENTE = "pendiente"
ESTADO_PROCESANDO = "procesando"
ESTADO_LISTO = "listo"
ESTADO_ERROR = "error"
ESTADOS_TERMINALES = frozenset({ESTADO_LISTO, ESTADO_ERROR})


class SincronizacionNoDisponibleError(Exception):
    """La sincronización no está habilitada o le falta configuración en este entorno."""


class EncolarJobError(Exception):
    """No se pudo registrar o encolar el job de generación."""


@dataclass(frozen=True)
class JobSincronizacion:
    job_id: str
    email_inspector: str
    estado: str
    s3_key: str | None = None
    error: str | None = None
    batch_job_id: str | None = None


class BatchSubmitter:
    """Encola el job de generación en AWS Batch (único punto que conoce el compute)."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _batch(self) -> Any:
        if self._client is None:
            cfg = self._settings
            if (
                not cfg.sincronizacion_batch_job_queue
                or not cfg.sincronizacion_batch_job_definition
            ):
                raise SincronizacionNoDisponibleError("Falta configuración de AWS Batch")
            self._client = boto3.client("batch", region_name=cfg.aws_region)
        return self._client

    async def enqueue_generation_job(
        self, job_id: str, email_inspector: str, origen: tuple[float, float] | None = None
    ) -> str:
        """Encola el job y devuelve el id que le asignó Batch.

        `origen` (latitud, longitud) viaja solo en el comando del job: no se guarda en la base.
        """
        cfg = self._settings
        argumentos_origen = (
            ["--origen-lat", repr(origen[0]), "--origen-lng", repr(origen[1])] if origen else []
        )
        respuesta = await asyncio.to_thread(
            self._batch().submit_job,
            jobName=f"sincronizacion-{job_id}",
            jobQueue=cfg.sincronizacion_batch_job_queue,
            jobDefinition=cfg.sincronizacion_batch_job_definition,
            containerOverrides={
                "command": [
                    "python",
                    "-m",
                    "app.jobs.generar_sincronizacion",
                    "--job-id",
                    job_id,
                    "--email",
                    email_inspector,
                    *argumentos_origen,
                ]
            },
        )
        return str(respuesta["jobId"])

    async def enqueue_subida_job(self, subida_id: str, email_inspector: str) -> str:
        """Encola el procesamiento de un ZIP subido (misma cola, otra job definition)."""
        cfg = self._settings
        if not cfg.subida_batch_job_definition:
            raise SincronizacionNoDisponibleError("Falta SUBIDA_BATCH_JOB_DEFINITION")
        respuesta = await asyncio.to_thread(
            self._batch().submit_job,
            jobName=f"subida-{subida_id}",
            jobQueue=cfg.sincronizacion_batch_job_queue,
            jobDefinition=cfg.subida_batch_job_definition,
            containerOverrides={
                "command": [
                    "python",
                    "-m",
                    "app.jobs.procesar_subida",
                    "--subida-id",
                    subida_id,
                    "--email",
                    email_inspector,
                ]
            },
        )
        return str(respuesta["jobId"])

    async def job_fallo(self, batch_job_id: str) -> bool:
        """True si Batch reporta el job como FAILED (el job no alcanzó a marcar `error`)."""
        respuesta = await asyncio.to_thread(self._batch().describe_jobs, jobs=[batch_job_id])
        jobs = respuesta.get("jobs", [])
        return bool(jobs) and jobs[0].get("status") == "FAILED"


def _base64_cloudfront(data: bytes) -> str:
    return base64.b64encode(data).decode().replace("+", "-").replace("=", "_").replace("/", "~")


# La API crea un firmador por petición: la clave de SSM se lee una sola vez por proceso.
_PEM_POR_PARAMETRO: dict[str, bytes] = {}


class CloudFrontUrlSigner:
    """Firma URLs de CloudFront con política *canned* (expiración) y la clave del key group."""

    def __init__(self, settings: Settings, private_key_pem: bytes | None = None) -> None:
        self._settings = settings
        self._private_key_pem = private_key_pem
        self._private_key: Any | None = None

    def _clave(self) -> Any:
        if self._private_key is None:
            pem = self._private_key_pem
            if pem is None:
                param = self._settings.sincronizacion_cloudfront_private_key_param
                if not param:
                    raise SincronizacionNoDisponibleError("Falta la clave de firmado de CloudFront")
                pem = _PEM_POR_PARAMETRO.get(param)
                if pem is None:
                    ssm = boto3.client("ssm", region_name=self._settings.aws_region)
                    valor = ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
                    pem = _PEM_POR_PARAMETRO[param] = valor.encode()
                self._private_key_pem = pem
            self._private_key = serialization.load_pem_private_key(pem, password=None)
        return self._private_key

    def firmar(self, s3_key: str, *, ahora: int | None = None) -> str:
        cfg = self._settings
        if not cfg.sincronizacion_cloudfront_domain:
            raise SincronizacionNoDisponibleError("Falta SINCRONIZACION_CLOUDFRONT_DOMAIN")
        return self._firmar(
            cfg.sincronizacion_cloudfront_domain,
            s3_key,
            firmada=cfg.sincronizacion_url_firmada,
            ttl=cfg.sincronizacion_url_ttl_segundos,
            ahora=ahora,
        )

    def firmar_foto(self, referencia: str, *, ahora: int | None = None) -> str:
        """URL de CloudFront de una foto o firma a partir de lo guardado en la BD.

        `referencia` es la clave S3 (`fotos/...`, `firmas/...`). Por compatibilidad también
        acepta la URL pública guardada antes de firmar: si es del dominio de fotos se vuelve a
        firmar su ruta; si es de otro host se devuelve tal cual.
        """
        cfg = self._settings
        dominio = cfg.fotos_cloudfront_domain
        clave = referencia
        if referencia.startswith(("http://", "https://")):
            partes = urlsplit(referencia)
            if not dominio or partes.netloc != dominio:
                return referencia
            clave = partes.path
        if not dominio:
            return referencia
        return self._firmar(
            dominio,
            clave.lstrip("/"),
            firmada=cfg.fotos_url_firmada,
            ttl=cfg.fotos_url_ttl_segundos,
            ahora=ahora,
        )

    def _firmar(
        self, dominio: str, s3_key: str, *, firmada: bool, ttl: int, ahora: int | None
    ) -> str:
        cfg = self._settings
        url = f"https://{dominio}/{s3_key}"
        if not firmada:
            return url
        if not cfg.sincronizacion_cloudfront_key_pair_id:
            raise SincronizacionNoDisponibleError("Falta SINCRONIZACION_CLOUDFRONT_KEY_PAIR_ID")
        expira = (ahora if ahora is not None else int(time.time())) + ttl
        politica = json.dumps(
            {
                "Statement": [
                    {
                        "Resource": url,
                        "Condition": {"DateLessThan": {"AWS:EpochTime": expira}},
                    }
                ]
            },
            separators=(",", ":"),
        ).encode()
        # CloudFront exige RSA PKCS#1 v1.5 con SHA-1 para sus URLs firmadas.
        firma = self._clave().sign(politica, padding.PKCS1v15(), hashes.SHA1())
        return (
            f"{url}?Expires={expira}&Signature={_base64_cloudfront(firma)}"
            f"&Key-Pair-Id={cfg.sincronizacion_cloudfront_key_pair_id}"
        )


class ZipUploader:
    """Sube el .zip generado al bucket privado de sincronización."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _s3(self) -> Any:
        if self._client is None:
            self._client = boto3.client("s3", region_name=self._settings.aws_region)
        return self._client

    async def subir(self, s3_key: str, contenido: bytes) -> None:
        if not self._settings.sincronizacion_s3_bucket:
            raise SincronizacionNoDisponibleError("Falta SINCRONIZACION_S3_BUCKET")
        await asyncio.to_thread(
            self._s3().put_object,
            Bucket=self._settings.sincronizacion_s3_bucket,
            Key=s3_key,
            Body=contenido,
            ContentType="application/zip",
        )
