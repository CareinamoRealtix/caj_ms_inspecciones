"""Almacenes de estado en memoria para las pruebas de los jobs.

Imitan a `JobStore` y `SubidaStore` (base de datos) sin necesitar una. El estado es de clase para
que varios objetos creados en una misma prueba vean los mismos datos, como ocurriría con la base;
la fixture de cada prueba llama a `reiniciar()`.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.infrastructure.clients.aws_sincronizacion import ESTADO_PENDIENTE, JobSincronizacion
from app.infrastructure.clients.aws_subida import ESTADO_PENDIENTE_CARGA, SubidaJob
from app.infrastructure.config.settings import Settings


class FakeJobStore:
    _datos: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, settings: Settings | None = None) -> None:
        pass

    async def crear(self, job_id: str, email_inspector: str) -> None:
        self._datos[job_id] = {
            "email_inspector": email_inspector,
            "estado": ESTADO_PENDIENTE,
            "s3_key": None,
            "error": None,
            "batch_job_id": None,
        }

    async def obtener(self, job_id: str) -> JobSincronizacion | None:
        fila = self._datos.get(job_id)
        return JobSincronizacion(job_id=job_id, **fila) if fila else None

    async def actualizar_estado(
        self,
        job_id: str,
        estado: str,
        *,
        s3_key: str | None = None,
        error: str | None = None,
        batch_job_id: str | None = None,
    ) -> None:
        fila = self._datos[job_id]
        fila["estado"] = estado
        for campo, valor in (("s3_key", s3_key), ("error", error), ("batch_job_id", batch_job_id)):
            if valor is not None:
                fila[campo] = valor


class FakeSubidaStore:
    _datos: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, settings: Settings | None = None) -> None:
        pass

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
        self._datos[subida_id] = {
            "email_inspector": email_inspector,
            "estado": ESTADO_PENDIENTE_CARGA,
            "s3_key": s3_key,
            "tamano_bytes": tamano_bytes,
            "sha256": sha256,
            "cantidad_levantamientos": cantidad_levantamientos,
            "resultados": [],
            "error": None,
            "batch_job_id": None,
        }

    async def obtener(self, subida_id: str) -> SubidaJob | None:
        fila = self._datos.get(subida_id)
        if not fila:
            return None
        return SubidaJob(subida_id=subida_id, **{**fila, "resultados": list(fila["resultados"])})

    async def actualizar_estado(
        self,
        subida_id: str,
        estado: str,
        *,
        error: str | None = None,
        reiniciar_resultados: bool = False,
    ) -> None:
        fila = self._datos[subida_id]
        fila["estado"] = estado
        if error is not None:
            fila["error"] = error
        if reiniciar_resultados:
            fila["resultados"] = []

    async def agregar_resultado(self, subida_id: str, resultado: dict[str, Any]) -> None:
        self._datos[subida_id]["resultados"].append(resultado)


def reiniciar() -> None:
    FakeJobStore._datos = {}  # type: ignore[misc]
    FakeSubidaStore._datos = {}
