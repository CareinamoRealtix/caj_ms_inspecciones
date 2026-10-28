import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.infrastructure.clients.aws_sincronizacion import CloudFrontUrlSigner
from app.infrastructure.config.settings import Settings


def test_url_firmada_tiene_firma_valida_y_expiracion() -> None:
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    settings = Settings(
        sincronizacion_cloudfront_domain="d111.cloudfront.net",
        sincronizacion_cloudfront_key_pair_id="K123",
        sincronizacion_url_firmada=True,
        sincronizacion_url_ttl_segundos=120,
        _env_file=None,
    )

    url = CloudFrontUrlSigner(settings, private_key_pem=pem).firmar(
        "sincronizacion/x.zip", ahora=1000
    )

    base, query = url.split("?")
    params = dict(p.split("=", 1) for p in query.split("&"))
    assert base == "https://d111.cloudfront.net/sincronizacion/x.zip"
    assert params["Expires"] == "1120"
    assert params["Key-Pair-Id"] == "K123"
    firma = base64.b64decode(
        params["Signature"].replace("-", "+").replace("_", "=").replace("~", "/")
    )
    # Política canned literal (formato exacto que exige CloudFront), escrita a mano a propósito:
    # construirla con la misma lógica del signer ocultaría un error de formato.
    politica = (
        b'{"Statement":[{"Resource":"https://d111.cloudfront.net/sincronizacion/x.zip",'
        b'"Condition":{"DateLessThan":{"AWS:EpochTime":1120}}}]}'
    )
    clave.public_key().verify(firma, politica, padding.PKCS1v15(), hashes.SHA1())


def test_sin_firma_devuelve_la_url_de_cloudfront_tal_cual() -> None:
    settings = Settings(
        sincronizacion_cloudfront_domain="d111.cloudfront.net",
        sincronizacion_url_firmada=False,
        _env_file=None,
    )

    url = CloudFrontUrlSigner(settings).firmar("sincronizacion/2026-10-07/x.zip")

    assert url == "https://d111.cloudfront.net/sincronizacion/2026-10-07/x.zip"


def _pem() -> tuple[rsa.RSAPrivateKey, bytes]:
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return clave, pem


def _settings_fotos(**extra: object) -> Settings:
    valores: dict[str, object] = {
        "fotos_cloudfront_domain": "fotos.cloudfront.net",
        "fotos_url_firmada": True,
        "fotos_url_ttl_segundos": 900,
        "sincronizacion_cloudfront_key_pair_id": "K123",
        **extra,
    }
    return Settings(_env_file=None, **valores)  # type: ignore[arg-type]


def test_foto_firmada_usa_dominio_y_ttl_de_fotos() -> None:
    clave, pem = _pem()

    url = CloudFrontUrlSigner(_settings_fotos(), private_key_pem=pem).firmar_foto(
        "fotos/a/b/0001.jpg", ahora=1000
    )

    base, query = url.split("?")
    params = dict(p.split("=", 1) for p in query.split("&"))
    assert base == "https://fotos.cloudfront.net/fotos/a/b/0001.jpg"
    assert params["Expires"] == "1900"
    assert params["Key-Pair-Id"] == "K123"
    firma = base64.b64decode(
        params["Signature"].replace("-", "+").replace("_", "=").replace("~", "/")
    )
    politica = (
        b'{"Statement":[{"Resource":"https://fotos.cloudfront.net/fotos/a/b/0001.jpg",'
        b'"Condition":{"DateLessThan":{"AWS:EpochTime":1900}}}]}'
    )
    clave.public_key().verify(firma, politica, padding.PKCS1v15(), hashes.SHA1())


def test_foto_con_url_publica_antigua_se_vuelve_a_firmar_por_su_ruta() -> None:
    _, pem = _pem()
    signer = CloudFrontUrlSigner(_settings_fotos(), private_key_pem=pem)

    url = signer.firmar_foto("https://fotos.cloudfront.net/firmas/x/y.png", ahora=1000)

    assert url.startswith("https://fotos.cloudfront.net/firmas/x/y.png?Expires=1900&")


def test_foto_de_otro_host_se_devuelve_tal_cual() -> None:
    signer = CloudFrontUrlSigner(_settings_fotos())

    assert (
        signer.firmar_foto("https://via.placeholder.com/300") == "https://via.placeholder.com/300"
    )


def test_foto_sin_firma_devuelve_url_de_cloudfront_sin_query() -> None:
    settings = _settings_fotos(fotos_url_firmada=False)

    url = CloudFrontUrlSigner(settings).firmar_foto("fotos/a.jpg")

    assert url == "https://fotos.cloudfront.net/fotos/a.jpg"


def test_foto_sin_dominio_configurado_devuelve_la_referencia() -> None:
    settings = Settings(_env_file=None)

    assert CloudFrontUrlSigner(settings).firmar_foto("fotos/a.jpg") == "fotos/a.jpg"
