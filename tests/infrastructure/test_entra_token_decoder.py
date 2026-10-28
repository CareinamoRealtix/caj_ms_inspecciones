import time

import jwt
import pytest

from app.infrastructure.clients.entra_token_decoder import (
    TokenDecodeError,
    decode_entra_token,
)


def _make_token(**claims: object) -> str:
    return jwt.encode(claims, "clave-de-prueba-suficientemente-larga", algorithm="HS256")


def test_decode_extracts_preferred_username_and_roles() -> None:
    token = _make_token(preferred_username="david@example.com", roles=["INSPECTOR"])

    claims = decode_entra_token(token)

    assert claims["preferred_username"] == "david@example.com"
    assert claims["roles"] == ["INSPECTOR"]


def test_decode_ignores_expired_tokens() -> None:
    hace_un_mes = int(time.time()) - 30 * 24 * 3600
    token = _make_token(
        preferred_username="david@example.com", roles=["INSPECTOR"], exp=hace_un_mes
    )

    claims = decode_entra_token(token)

    assert claims["preferred_username"] == "david@example.com"


def test_decode_ignores_wrong_signature() -> None:
    token = jwt.encode(
        {"preferred_username": "david@example.com"}, "clave-cualquiera-suficientemente-larga"
    )

    claims = decode_entra_token(token)

    assert claims["preferred_username"] == "david@example.com"


def test_decode_rejects_malformed_token() -> None:
    with pytest.raises(TokenDecodeError):
        decode_entra_token("esto-no-es-un-jwt")
