import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.connection import Database, DatabaseUnavailableError
from app.infrastructure.logging.config import configure_logging, reset_request_id, set_request_id
from app.presentation.api.exception_handlers import unexpected_exception_handler
from app.presentation.api.routers.health import router as health_router
from app.presentation.api.routers.inspecciones import router as inspecciones_router
from app.presentation.api.routers.inspectores import router as inspectores_router
from app.presentation.api.routers.jobs import router as jobs_router
from app.presentation.api.routers.notificaciones import router as notificaciones_router
from app.presentation.api.routers.sincronizacion import router as sincronizacion_router
from app.presentation.api.routers.subidas import router as subidas_router

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        await app.state.database.connect()
        logger.info("Database pool initialized", extra={"event": "database_connected"})
    except DatabaseUnavailableError:
        logger.warning(
            "Database unavailable during startup; readiness will retry",
            extra={"event": "database_unavailable"},
        )

    yield

    await app.state.database.close()
    logger.info("Database pool closed", extra={"event": "database_disconnected"})


def create_app() -> FastAPI:
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.state.database = Database(settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started_at = time.perf_counter()
        logger.info("Request started", extra={"event": "request_started"})
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "Request completed",
                extra={"event": "request_completed", "duration_ms": duration_ms},
            )
            reset_request_id(token)

    application.add_exception_handler(Exception, unexpected_exception_handler)
    application.include_router(health_router, prefix=settings.api_prefix)
    application.include_router(inspectores_router, prefix=settings.api_prefix)
    application.include_router(inspecciones_router, prefix=settings.api_prefix)
    application.include_router(notificaciones_router, prefix=settings.api_prefix)
    application.include_router(jobs_router, prefix=settings.api_prefix)
    application.include_router(sincronizacion_router, prefix=settings.api_prefix)
    application.include_router(subidas_router, prefix=settings.api_prefix)
    return application


app = create_app()
