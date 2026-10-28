from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.database.connection import DatabaseUnavailableError
from app.infrastructure.logging.config import get_request_id
from app.presentation.api.dependencies.database import DatabaseHealth, get_database
from app.presentation.api.schemas.health import ErrorResponse, HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(service=settings.app_name)


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}},
)
async def ready(
    request: Request,
    database: Annotated[DatabaseHealth, Depends(get_database)],
) -> ReadyResponse | JSONResponse:
    try:
        await database.ping()
    except DatabaseUnavailableError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "DATABASE_UNAVAILABLE",
                "message": "Database is unavailable",
                "request_id": get_request_id() or request.state.request_id,
            },
        )
    return ReadyResponse()
