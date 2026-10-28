"""Decodifica JWT de Entra ID sin verificarlos.

La validación (firma, `exp`, `aud`, `iss`) queda a cargo del API Gateway, que ya
autenticó la solicitud antes de que llegue a este microservicio. Acá solo se confía
en el contenido del token y se extraen sus claims.
"""
from __future__ import annotations

from typing import Any

import jwt


class TokenDecodeError(Exception):
    """El token entrante no tiene forma de JWT (no se puede decodificar)."""


def decode_entra_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise TokenDecodeError(f"Token malformado: {exc}") from exc
