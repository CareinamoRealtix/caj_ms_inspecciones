from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from app.infrastructure.config.settings import Settings


class DatabaseUnavailableError(Exception):
    """La conexión a PostgreSQL no está disponible."""


class Database:
    """Administra un pool asyncpg reutilizable durante la vida de la aplicación."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool[Any] | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._pool is not None:
            return

        async with self._connect_lock:
            if self._pool is not None:
                return
            try:
                self._pool = await asyncpg.create_pool(
                    host=self._settings.database_host,
                    port=self._settings.database_port,
                    database=self._settings.database_name,
                    user=self._settings.database_user,
                    password=self._settings.database_password,
                    min_size=self._settings.database_pool_min_size,
                    max_size=self._settings.database_pool_max_size,
                    timeout=self._settings.database_connect_timeout,
                    ssl=self._settings.database_ssl_mode,
                    server_settings={"search_path": f"{self._settings.database_schema},public"},
                )
            except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
                raise DatabaseUnavailableError from exc

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool[Any]:
        if self._pool is None:
            raise DatabaseUnavailableError("Pool no inicializado")
        return self._pool

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:  # type: ignore[type-arg]
        await self.connect()
        async with self.pool.acquire() as conn:
            yield conn

    async def ping(self) -> None:
        try:
            await self.connect()
            if self._pool is None:  # pragma: no cover - invariant defensiva
                raise DatabaseUnavailableError
            version = await self._pool.fetchval("SELECT PostGIS_Version();")
        except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
            raise DatabaseUnavailableError from exc

        if not isinstance(version, str) or not version:
            raise DatabaseUnavailableError
