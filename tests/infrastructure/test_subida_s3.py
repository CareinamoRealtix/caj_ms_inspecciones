import pytest
from botocore.exceptions import ClientError

from app.infrastructure.clients.aws_subida import SubidaS3
from app.infrastructure.config.settings import Settings


class ClienteS3Falso:
    def __init__(self, codigo: str | None = None, tamano: int = 0) -> None:
        self.codigo = codigo
        self.tamano = tamano

    def head_object(self, Bucket: str, Key: str) -> dict:
        if self.codigo:
            raise ClientError({"Error": {"Code": self.codigo, "Message": "x"}}, "HeadObject")
        return {"ContentLength": self.tamano}


def _s3(cliente: ClienteS3Falso) -> SubidaS3:
    return SubidaS3(Settings(subida_s3_bucket="b", _env_file=None), cliente)


async def test_devuelve_el_tamano_si_el_zip_existe() -> None:
    assert await _s3(ClienteS3Falso(tamano=123)).tamano_zip("k") == 123


@pytest.mark.parametrize("codigo", ["404", "NoSuchKey", "NotFound", "403", "AccessDenied"])
async def test_zip_inexistente_se_trata_como_no_subido(codigo: str) -> None:
    # Sin s3:ListBucket, S3 responde 403 (no 404) para una key que no existe.
    assert await _s3(ClienteS3Falso(codigo)).tamano_zip("k") is None


async def test_otros_errores_de_s3_se_propagan() -> None:
    with pytest.raises(ClientError):
        await _s3(ClienteS3Falso("500")).tamano_zip("k")
