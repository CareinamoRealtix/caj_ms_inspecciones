"""Orquesta la sincronización offline asíncrona (HU.12): disparo, estado y descarga."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.infrastructure.clients.aws_sincronizacion import (
    ESTADO_ERROR,
    ESTADO_LISTO,
    ESTADO_PENDIENTE,
    ESTADOS_TERMINALES,
    BatchSubmitter,
    CloudFrontUrlSigner,
    EncolarJobError,
    JobSincronizacion,
    SincronizacionNoDisponibleError,
)
from app.infrastructure.config.settings import Settings
from app.infrastructure.database.sincronizacion_estado_repository import JobStore

logger = logging.getLogger(__name__)

INTERVALO_CONSULTA_SEGUNDOS = 1.5


class JobNoEncontradoError(Exception):
    """El job no existe o no pertenece al inspector que lo consulta."""


@dataclass(frozen=True)
class EstadoJob:
    job_id: str
    estado: str
    url_firmada: str | None = None
    error: str | None = None


class SincronizacionService:
    def __init__(
        self,
        settings: Settings,
        store: JobStore,
        submitter: BatchSubmitter,
        signer: CloudFrontUrlSigner,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._store = store
        self._submitter = submitter
        self._signer = signer
        self._sleep = sleep
        self._reloj = reloj

    def _verificar_habilitada(self) -> None:
        if not self._settings.sincronizacion_habilitada:
            raise SincronizacionNoDisponibleError("Sincronización deshabilitada en este entorno")

    async def iniciar(self, email_inspector: str, origen: tuple[float, float] | None = None) -> str:
        """Registra el job y lo encola en Batch. Devuelve el `job_id`.

        `origen` (latitud, longitud) es el punto de partida de las rutas óptimas del paquete.
        """
        self._verificar_habilitada()
        job_id = str(uuid.uuid4())
        await self._store.crear(job_id, email_inspector)
        try:
            batch_job_id = await self._submitter.enqueue_generation_job(
                job_id, email_inspector, origen
            )
            await self._store.actualizar_estado(job_id, ESTADO_PENDIENTE, batch_job_id=batch_job_id)
        except SincronizacionNoDisponibleError:
            raise
        except Exception as exc:
            logger.exception(
                "No se pudo encolar el job de sincronización",
                extra={"event": "sincronizacion_encolar_failed", "job_id": job_id},
            )
            await self._store.actualizar_estado(
                job_id, ESTADO_ERROR, error="No se pudo iniciar la sincronización"
            )
            raise EncolarJobError from exc
        logger.info(
            "Job de sincronización encolado",
            extra={"event": "sincronizacion_encolado", "job_id": job_id},
        )
        return job_id

    async def consultar(self, job_id: str, email_inspector: str, espera: int) -> EstadoJob:
        """Long polling: espera hasta `espera` s a que el job termine y devuelve su estado."""
        self._verificar_habilitada()
        espera = max(0, min(espera, self._settings.sincronizacion_long_polling_max_segundos))
        limite = self._reloj() + espera
        while True:
            job = await self._store.obtener(job_id)
            if job is None or job.email_inspector != email_inspector:
                # Mismo error para "no existe" y "es de otro inspector": no revela jobs ajenos.
                raise JobNoEncontradoError(job_id)
            if job.estado in ESTADOS_TERMINALES:
                return self._respuesta(job)
            if self._reloj() >= limite:
                return self._respuesta(await self._detectar_fallo_de_batch(job))
            await self._sleep(INTERVALO_CONSULTA_SEGUNDOS)

    async def _detectar_fallo_de_batch(self, job: JobSincronizacion) -> JobSincronizacion:
        """Cubre los fallos que el job no alcanza a reportar (OOM, imagen que no baja, etc.)."""
        if not job.batch_job_id:
            return job
        try:
            fallo = await self._submitter.job_fallo(job.batch_job_id)
        except Exception:
            logger.exception(
                "No se pudo consultar el estado del job en Batch",
                extra={"event": "sincronizacion_describe_failed", "job_id": job.job_id},
            )
            return job
        if not fallo:
            return job
        mensaje = "No se pudo generar la sincronización"
        await self._store.actualizar_estado(job.job_id, ESTADO_ERROR, error=mensaje)
        return JobSincronizacion(
            job.job_id,
            job.email_inspector,
            ESTADO_ERROR,
            error=mensaje,
            batch_job_id=job.batch_job_id,
        )

    def _respuesta(self, job: JobSincronizacion) -> EstadoJob:
        if job.estado == ESTADO_LISTO and job.s3_key:
            return EstadoJob(job.job_id, job.estado, url_firmada=self._signer.firmar(job.s3_key))
        if job.estado == ESTADO_ERROR:
            return EstadoJob(
                job.job_id, job.estado, error=job.error or "Error en la sincronización"
            )
        return EstadoJob(job.job_id, job.estado)
