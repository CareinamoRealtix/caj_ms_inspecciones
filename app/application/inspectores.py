"""Transformación compartida de usuarios de Microsoft Graph."""

from typing import Any

from app.presentation.api.schemas.inspectores import InspectorItem


def build_inspector_items(members: list[dict[str, Any]]) -> list[InspectorItem]:
    """Construye el contrato público y completa mail con userPrincipalName."""
    return [
        InspectorItem(
            displayName=member.get("displayName"),
            mail=member.get("mail") or member.get("userPrincipalName"),
        )
        for member in members
    ]
