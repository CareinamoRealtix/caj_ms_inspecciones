from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
