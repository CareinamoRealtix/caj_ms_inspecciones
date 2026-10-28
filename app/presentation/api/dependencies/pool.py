from typing import Annotated

import asyncpg
from fastapi import Depends, Request

from app.infrastructure.database.connection import Database, DatabaseUnavailableError


def get_db(request: Request) -> Database:
    return request.app.state.database  # type: ignore[no-any-return]


async def get_pool(db: Annotated[Database, Depends(get_db)]) -> asyncpg.Pool:  # type: ignore[type-arg]
    await db.connect()
    return db.pool


__all__ = ["DatabaseUnavailableError", "get_db", "get_pool"]
