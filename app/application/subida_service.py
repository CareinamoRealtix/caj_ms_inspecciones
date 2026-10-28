"""Orquesta la subida de levantamientos por ZIP (HU.12, Etapa 2): carga, confirmación y estado."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.clients.aws_sincronizacion import (
    BatchSubmitter,
    EncolarJobError,
    SincronizacionNoDisponibleError,
)
from app.infrastructure.clients.aws_subida import (
    ESTADO_ERROR,
    ESTADO_PENDIENTE,
    ESTADO_PENDIENTE_CARGA,
    ESTADOS_TERMINALES,
    SubidaJob,
    SubidaS3,
)
from app.infrastructure.config.settings import Settings
from app.infrastructure.database.sincronizacion_estado_repository import SubidaStore

logger = logging.getLogger(__name__)

INTERVALO_CONSULTA_SEGUNDOS = 1.5
MENSAJE_ERROR_GENERICO = "No se pudo procesar la subida"


class SubidaNoEncontradaError(Exception):
    """La subida no existe o no pertenece al inspector que la consulta."""


class SubidaFueraDeLimiteError(Exception):
    """El ZIP o la cantidad de levantamientos superan los límites configurados."""


class SubidaCargaIncompletaError(Exception):
    """El ZIP no está en S3 o su tamaño no coincide con el declarado."""


@dataclass(frozen=True)
class SubidaCreada:
    subida_id: str
    url_carga: str
    vence_en: datetime


@dataclass(frozen=True)
class EstadoSubida:
    subida_id: str
    estado: str
    resultados: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class SubidaService:
    def __init__(
        self,
        settings: Settings,
        store: SubidaStore,
        s3: SubidaS3,
        submitter: BatchSubmitter,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._store = store
        self._s3 = s3
        self._submitter = submitter
        self._sleep = sleep
        self._reloj = reloj

    def _verificar_habilitada(self) -> None:
        if not self._settings.sincronizacion_habilitada:
            raise SincronizacionNoDisponibleError("Sincronización deshabilitada en este entorno")

    @staticmethod
    def clave_zip(subida_id: str, ahora: datetime | None = None) -> str:
        fecha = (ahora or datetime.now(UTC)).strftime("%Y-%m-%d")
        # subida_id es un UUID no adivinable; el email (PII) no va en la key.
        return f"subidas/{fecha}/{subida_id}.zip"

    async def iniciar(
        self, email_inspector: str, tamano_bytes: int, sha256: str, cantidad_levantamientos: int
    ) -> SubidaCreada:
        """Registra la subida y entrega la URL prefirmada donde la app deja el ZIP."""
        self._verificar_habilitada()
        cfg = self._settings
        if tamano_bytes > cfg.subida_max_bytes:
            raise SubidaFueraDeLimiteError("El ZIP supera el tamaño máximo permitido")
        if cantidad_levantamientos > cfg.subida_max_levantamientos:
            raise SubidaFueraDeLimiteError("El ZIP supera la cantidad máxima de levantamientos")

        subida_id = str(uuid.uuid4())
        s3_key = self.clave_zip(subida_id)
        await self._store.crear(
            subida_id,
            email_inspector,
            s3_key=s3_key,
            tamano_bytes=tamano_bytes,
            sha256=sha256.lower(),
            cantidad_levantamientos=cantidad_levantamientos,
        )
        url = await self._s3.url_carga(s3_key, tamano_bytes)
        vence_en = datetime.fromtimestamp(time.time() + cfg.subida_url_ttl_segundos, UTC)
        logger.info(
            "Subida registrada",
            extra={"event": "subida_creada", "subida_id": subida_id, "bytes": tamano_bytes},
        )
        return SubidaCreada(subida_id, url, vence_en)

    async def _obtener_propia(self, subida_id: str, email_inspector: str) -> SubidaJob:
        subida = await self._store.obtener(subida_id)
        if subida is None or subida.email_inspector != email_inspector:
            # Mismo error para "no existe" y "es de otro inspector": no revela subidas ajenas.
            raise SubidaNoEncontradaError(subida_id)
        return subida

    async def confirmar(self, subida_id: str, email_inspector: str) -> EstadoSubida:
        """Verifica que el ZIP llegó a S3 y encola su procesamiento (idempotente)."""
        self._verificar_habilitada()
        subida = await self._obtener_propia(subida_id, email_inspector)
        if subida.estado != ESTADO_PENDIENTE_CARGA:
            return self._respuesta(subida)  # reintento de `confirmar`: ya está en marcha

        tamano = await self._s3.tamano_zip(subida.s3_key)
        if tamano is None or tamano != subida.tamano_bytes:
            raise SubidaCargaIncompletaError(subida_id)
        if not await self._store.reservar_confirmacion(subida_id):
            return self._respuesta(await self._obtener_propia(subida_id, email_inspector))

        try:
            batch_job_id = await self._submitter.enqueue_subida_job(subida_id, email_inspector)
            await self._store.marcar_confirmada(subida_id, batch_job_id)
        except SincronizacionNoDisponibleError:
            raise
        except Exception as exc:
            logger.exception(
                "No se pudo encolar el procesamiento de la subida",
                extra={"event": "subida_encolar_failed", "subida_id": subida_id},
            )
            await self._store.actualizar_estado(
                subida_id, ESTADO_ERROR, error="No se pudo iniciar el procesamiento"
            )
            raise EncolarJobError from exc
        return EstadoSubida(subida_id, ESTADO_PENDIENTE)

    async def consultar(self, subida_id: str, email_inspector: str, espera: int) -> EstadoSubida:
        """Long polling: espera hasta `espera` s a que termine y devuelve estado y resultados."""
        self._verificar_habilitada()
        espera = max(0, min(espera, self._settings.sincronizacion_long_polling_max_segundos))
        limite = self._reloj() + espera
        while True:
            subida = await self._obtener_propia(subida_id, email_inspector)
            if subida.estado in ESTADOS_TERMINALES:
                return self._respuesta(subida)
            if self._reloj() >= limite:
                return self._respuesta(await self._detectar_fallo_de_batch(subida))
            await self._sleep(INTERVALO_CONSULTA_SEGUNDOS)

    async def _detectar_fallo_de_batch(self, subida: SubidaJob) -> SubidaJob:
        """Cubre los fallos que el job no alcanza a reportar (OOM, imagen que no baja, etc.)."""
        if not subida.batch_job_id:
            return subida
        try:
            fallo = await self._submitter.job_fallo(subida.batch_job_id)
        except Exception:
            logger.exception(
                "No se pudo consultar el estado de la subida en Batch",
                extra={"event": "subida_describe_failed", "subida_id": subida.subida_id},
            )
            return subida
        if not fallo:
            return subida
        await self._store.actualizar_estado(
            subida.subida_id, ESTADO_ERROR, error=MENSAJE_ERROR_GENERICO
        )
        return SubidaJob(
            subida.subida_id,
            subida.email_inspector,
            ESTADO_ERROR,
            subida.s3_key,
            subida.tamano_bytes,
            subida.sha256,
            subida.cantidad_levantamientos,
            resultados=subida.resultados,
            error=MENSAJE_ERROR_GENERICO,
            batch_job_id=subida.batch_job_id,
        )

    @staticmethod
    def _respuesta(subida: SubidaJob) -> EstadoSubida:
        error = subida.error or (MENSAJE_ERROR_GENERICO if subida.estado == ESTADO_ERROR else None)
        return EstadoSubida(subida.subida_id, subida.estado, subida.resultados, error)
