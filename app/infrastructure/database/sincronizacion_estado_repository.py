"""Estado de los jobs de sincronización en la base (punto neutral entre la API y Batch).

Reemplaza a las tablas de DynamoDB: la API y los jobs de Batch comparten estas dos tablas del
esquema `inspecciones`. Los registros son temporales: `expira_en` los vuelve invisibles y se borran
los vencidos al crear uno nuevo.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from app.infrastructure.clients.aws_sincronizacion import ESTADO_PENDIENTE, JobSincronizacion
from app.infrastructure.clients.aws_subida import (
    ESTADO_PENDIENTE as SUBIDA_PENDIENTE,
)
from app.infrastructure.clients.aws_subida import (
    ESTADO_PENDIENTE_CARGA,
    SubidaJob,
)
from app.infrastructure.config.settings import Settings


def _uuid(valor: str) -> uuid.UUID | None:
    """El id llega de la ruta de la API: si no es un UUID, el registro simplemente no existe."""
    try:
        return uuid.UUID(valor)
    except ValueError:
        return None


class JobStore:
    """Estado de la descarga (`inspecciones.sincronizacion_job`)."""

    def __init__(self, pool: asyncpg.Pool[Any], settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    async def crear(self, job_id: str, email_inspector: str) -> None:
        await self._pool.execute("DELETE FROM sincronizacion_job WHERE expira_en < NOW()")
        await self._pool.execute(
            """
            INSERT INTO sincronizacion_job (job_id, email_inspector, estado, expira_en)
            VALUES ($1, $2, $3, NOW() + make_interval(hours => $4))
            """,
            uuid.UUID(job_id),
            email_inspector,
            ESTADO_PENDIENTE,
            self._settings.sincronizacion_job_ttl_horas,
        )

    async def obtener(self, job_id: str) -> JobSincronizacion | None:
        clave = _uuid(job_id)
        if clave is None:
            return None
        fila = await self._pool.fetchrow(
            """
            SELECT job_id, email_inspector, estado, s3_key, error, batch_job_id
            FROM sincronizacion_job
            WHERE job_id = $1 AND expira_en > NOW()
            """,
            clave,
        )
        if fila is None:
            return None
        return JobSincronizacion(
            job_id=str(fila["job_id"]),
            email_inspector=fila["email_inspector"],
            estado=fila["estado"],
            s3_key=fila["s3_key"],
            error=fila["error"],
            batch_job_id=fila["batch_job_id"],
        )

    async def actualizar_estado(
        self,
        job_id: str,
        estado: str,
        *,
        s3_key: str | None = None,
        error: str | None = None,
        batch_job_id: str | None = None,
    ) -> None:
        # Un argumento None conserva el valor que ya tenía la columna.
        await self._pool.execute(
            """
            UPDATE sincronizacion_job
            SET estado = $2,
                s3_key = COALESCE($3, s3_key),
                error = COALESCE($4, error),
                batch_job_id = COALESCE($5, batch_job_id),
                fecha_modificacion = NOW()
            WHERE job_id = $1
            """,
            uuid.UUID(job_id),
            estado,
            s3_key,
            error,
            batch_job_id,
        )


def _resultados(valor: Any) -> list[dict[str, Any]]:
    # Sin codec de JSONB en el pool, asyncpg devuelve el JSON como texto.
    if isinstance(valor, str):
        valor = json.loads(valor)
    return list(valor or [])


class SubidaStore:
    """Estado de la subida por ZIP (`inspecciones.subida_levantamiento`)."""

    def __init__(self, pool: asyncpg.Pool[Any], settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    async def crear(
        self,
        subida_id: str,
        email_inspector: str,
        *,
        s3_key: str,
        tamano_bytes: int,
        sha256: str,
        cantidad_levantamientos: int,
    ) -> None:
        await self._pool.execute("DELETE FROM subida_levantamiento WHERE expira_en < NOW()")
        await self._pool.execute(
            """
            INSERT INTO subida_levantamiento (
                subida_id, email_inspector, estado, s3_key, tamano_bytes, sha256,
                cantidad_levantamientos, expira_en
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW() + make_interval(hours => $8))
            """,
            uuid.UUID(subida_id),
            email_inspector,
            ESTADO_PENDIENTE_CARGA,
            s3_key,
            tamano_bytes,
            sha256,
            cantidad_levantamientos,
            self._settings.subida_job_ttl_horas,
        )

    async def obtener(self, subida_id: str) -> SubidaJob | None:
        clave = _uuid(subida_id)
        if clave is None:
            return None
        fila = await self._pool.fetchrow(
            """
            SELECT subida_id, email_inspector, estado, s3_key, tamano_bytes, sha256,
                   cantidad_levantamientos, resultados, error, batch_job_id
            FROM subida_levantamiento
            WHERE subida_id = $1 AND expira_en > NOW()
            """,
            clave,
        )
        if fila is None:
            return None
        return SubidaJob(
            subida_id=str(fila["subida_id"]),
            email_inspector=fila["email_inspector"],
            estado=fila["estado"],
            s3_key=fila["s3_key"],
            tamano_bytes=int(fila["tamano_bytes"]),
            sha256=fila["sha256"],
            cantidad_levantamientos=int(fila["cantidad_levantamientos"]),
            resultados=_resultados(fila["resultados"]),
            error=fila["error"],
            batch_job_id=fila["batch_job_id"],
        )

    async def marcar_confirmada(self, subida_id: str, batch_job_id: str) -> None:
        await self._pool.execute(
            """
            UPDATE subida_levantamiento
            SET estado = $2, batch_job_id = $3, fecha_modificacion = NOW()
            WHERE subida_id = $1
            """,
            uuid.UUID(subida_id),
            SUBIDA_PENDIENTE,
            batch_job_id,
        )

    async def reservar_confirmacion(self, subida_id: str) -> bool:
        """Pasa de `pendiente_carga` a `pendiente` de forma atómica; False si ya se confirmó.

        Evita encolar dos veces el mismo ZIP si la app reintenta `confirmar`.
        """
        resultado = await self._pool.execute(
            """
            UPDATE subida_levantamiento
            SET estado = $2, fecha_modificacion = NOW()
            WHERE subida_id = $1 AND estado = $3
            """,
            uuid.UUID(subida_id),
            SUBIDA_PENDIENTE,
            ESTADO_PENDIENTE_CARGA,
        )
        return str(resultado) == "UPDATE 1"

    async def actualizar_estado(
        self,
        subida_id: str,
        estado: str,
        *,
        error: str | None = None,
        reiniciar_resultados: bool = False,
    ) -> None:
        # Un reintento de Batch parte de cero: sin reiniciar, los resultados se duplicarían.
        await self._pool.execute(
            """
            UPDATE subida_levantamiento
            SET estado = $2,
                error = COALESCE($3, error),
                resultados = CASE WHEN $4 THEN '[]'::jsonb ELSE resultados END,
                fecha_modificacion = NOW()
            WHERE subida_id = $1
            """,
            uuid.UUID(subida_id),
            estado,
            error,
            reiniciar_resultados,
        )

    async def agregar_resultado(self, subida_id: str, resultado: dict[str, Any]) -> None:
        await self._pool.execute(
            """
            UPDATE subida_levantamiento
            SET resultados = resultados || $2::jsonb, fecha_modificacion = NOW()
            WHERE subida_id = $1
            """,
            uuid.UUID(subida_id),
            json.dumps([resultado]),
        )
