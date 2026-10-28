import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.infrastructure.logging.config import get_request_id

logger = logging.getLogger(__name__)


async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = get_request_id() or getattr(request.state, "request_id", "unknown")
    logger.exception("Unexpected application error", extra={"event": "unexpected_error"})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Unexpected internal error",
            "request_id": request_id,
        },
    )
