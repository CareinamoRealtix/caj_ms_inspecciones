"""Contratos HTTP del endpoint de inspectores."""

from pydantic import BaseModel


class InspectorItem(BaseModel):
    displayName: str | None = None
    mail: str | None = None


class InspectoresResponse(BaseModel):
    total: int
    inspectores: list[InspectorItem]
