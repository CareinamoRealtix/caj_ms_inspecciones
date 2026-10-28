from typing import Protocol

from fastapi import Request


class DatabaseHealth(Protocol):
    async def ping(self) -> None: ...


def get_database(request: Request) -> DatabaseHealth:
    return request.app.state.database
