import hashlib
import io
import json
import uuid
import zipfile
from types import SimpleNamespace

import boto3
import pytest
from fakes import FakeSubidaStore, reiniciar
from moto import mock_aws

from app.infrastructure.clients.aws_subida import SubidaS3
from app.infrastructure.config.settings import Settings
from app.jobs.procesar_subida import procesar

BUCKET_ZIP = "subidas-test"
BUCKET_FOTOS = "fotos-test"
EMAIL = "insp@example.com"
JPG = b"\xff\xd8\xff\xe0" + b"0" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class FakeServicio:
    """Imita `finalizar_levantamiento_batch`: falla la inspección que se le indique."""

    def __init__(self, fallan: set[str] | None = None) -> None:
        self.fallan = fallan or set()
        self.recibidos: list = []

    async def finalizar_levantamiento_batch(self, body, usuario):  # type: ignore[no-untyped-def]
        item = body.levantamientos[0]
        self.recibidos.append((item, usuario))
        id_insp = item.id_inspeccion
        ok = str(id_insp) not in self.fallan
        return SimpleNamespace(
            resultados=[
                SimpleNamespace(
                    id_inspeccion=id_insp,
                    exito=ok,
                    repetido=False,
                    id_levantamiento=uuid.uuid4() if ok else None,
                    codigo_error=None if ok else "ya_finalizada",
                    mensaje="ok" if ok else None,
                )
            ]
        )


def levantamiento(id_insp: str, fotos: list[str], firma: str | None = None) -> dict:
    return {
        "id_operacion": str(uuid.uuid4()),
        "id_inspeccion": id_insp,
        "condicion_bien": "BUENO",
        "estado_ocupacion": "DESOCUPADO",
        "fecha_levantamiento": "2026-10-01",
        "archivo_firma": firma,
        "fotografias": [
            {"archivo": f, "es_foto_principal": i == 0, "es_visible_geovisor": True}
            for i, f in enumerate(fotos)
        ],
    }


def construir_zip(items: list[dict], extra: dict[str, bytes] | None = None, **manifest) -> bytes:
    manifest = {"version": 1, "cantidad_levantamientos": len(items), **manifest}
    archivos = {
        "manifest.json": json.dumps(manifest).encode(),
        "levantamientos.json": json.dumps({"levantamientos": items}).encode(),
        **(extra or {}),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return buffer.getvalue()


@pytest.fixture
def aws():  # type: ignore[no-untyped-def]
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET_ZIP)
        s3.create_bucket(Bucket=BUCKET_FOTOS)
        reiniciar()
        settings = Settings(
            subida_s3_bucket=BUCKET_ZIP,
            fotos_s3_bucket=BUCKET_FOTOS,
            fotos_cloudfront_domain="fotos.test",
            subida_max_bytes_por_imagen=1000,
            _env_file=None,
        )
        yield settings, s3, None


async def _subir(aws, contenido: bytes, *, cantidad: int, sha: str | None = None) -> str:  # type: ignore[no-untyped-def]
    settings, s3, _ = aws
    subida_id = str(uuid.uuid4())
    clave = f"subidas/2026-10-01/{subida_id}.zip"
    s3.put_object(Bucket=BUCKET_ZIP, Key=clave, Body=contenido)
    await FakeSubidaStore(settings).crear(
        subida_id,
        EMAIL,
        s3_key=clave,
        tamano_bytes=len(contenido),
        sha256=sha or hashlib.sha256(contenido).hexdigest(),
        cantidad_levantamientos=cantidad,
    )
    return subida_id


async def _ejecutar(aws, subida_id: str, servicio: FakeServicio) -> str:  # type: ignore[no-untyped-def]
    settings = aws[0]
    return await procesar(
        subida_id,
        EMAIL,
        servicio=servicio,  # type: ignore[arg-type]
        store=FakeSubidaStore(settings),
        s3=SubidaS3(settings),
        settings=settings,
    )


def _claves_fotos(aws) -> list[str]:  # type: ignore[no-untyped-def]
    respuesta = aws[1].list_objects_v2(Bucket=BUCKET_FOTOS)
    return sorted(o["Key"] for o in respuesta.get("Contents", []))


async def test_flujo_completo_sube_imagenes_y_finaliza(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    items = [levantamiento(insp, ["fotos/a/1.jpg", "fotos/a/2.png"], "firmas/a.png")]
    zip_bytes = construir_zip(
        items,
        {"fotos/a/1.jpg": JPG, "fotos/a/2.png": PNG, "firmas/a.png": PNG},
    )
    subida_id = await _subir(aws, zip_bytes, cantidad=1)
    servicio = FakeServicio()

    assert await _ejecutar(aws, subida_id, servicio) == "listo"

    id_op = items[0]["id_operacion"]
    assert _claves_fotos(aws) == [
        f"firmas/{insp}/{id_op}.png",
        f"fotos/{insp}/{id_op}/0001.jpg",
        f"fotos/{insp}/{id_op}/0002.png",
    ]
    item, usuario = servicio.recibidos[0]
    assert usuario == EMAIL
    assert [f.url for f in item.fotografias] == [
        f"fotos/{insp}/{id_op}/0001.jpg",
        f"fotos/{insp}/{id_op}/0002.png",
    ]
    assert item.fotografias[0].es_foto_principal is True
    assert item.url_firma_inspector == f"firmas/{insp}/{id_op}.png"

    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None and subida.estado == "listo"
    assert [r["exito"] for r in subida.resultados] == [True]


async def test_un_levantamiento_malo_no_aborta_el_resto(aws) -> None:  # type: ignore[no-untyped-def]
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    items = [
        levantamiento(a, ["fotos/a.jpg"]),
        levantamiento(b, ["fotos/falta.jpg"]),  # el archivo no está en el ZIP
        levantamiento(c, ["fotos/c.jpg"]),
    ]
    zip_bytes = construir_zip(items, {"fotos/a.jpg": JPG, "fotos/c.jpg": JPG})
    subida_id = await _subir(aws, zip_bytes, cantidad=3)

    assert await _ejecutar(aws, subida_id, FakeServicio()) == "parcial"

    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None
    assert [(r["id_inspeccion"], r["exito"]) for r in subida.resultados] == [
        (a, True),
        (b, False),
        (c, True),
    ]
    assert subida.resultados[1]["codigo_error"] == "archivo_faltante"
    assert not any(b in k for k in _claves_fotos(aws))  # nada subido para el que falló


async def test_error_de_negocio_se_reporta_por_inspeccion(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    zip_bytes = construir_zip([levantamiento(insp, [])])
    subida_id = await _subir(aws, zip_bytes, cantidad=1)

    assert await _ejecutar(aws, subida_id, FakeServicio(fallan={insp})) == "parcial"
    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None and subida.resultados[0]["codigo_error"] == "ya_finalizada"


async def test_imagen_que_no_es_imagen_se_rechaza_por_contenido(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    zip_bytes = construir_zip([levantamiento(insp, ["fotos/x.jpg"])], {"fotos/x.jpg": b"<svg/>"})
    subida_id = await _subir(aws, zip_bytes, cantidad=1)

    assert await _ejecutar(aws, subida_id, FakeServicio()) == "parcial"
    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None and subida.resultados[0]["codigo_error"] == "imagen_invalida"
    assert _claves_fotos(aws) == []


async def test_imagen_mas_grande_que_el_limite_se_rechaza(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    grande = JPG + b"0" * 2000  # el límite del fixture es 1000 bytes
    zip_bytes = construir_zip([levantamiento(insp, ["fotos/x.jpg"])], {"fotos/x.jpg": grande})
    subida_id = await _subir(aws, zip_bytes, cantidad=1)

    assert await _ejecutar(aws, subida_id, FakeServicio()) == "parcial"
    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None and subida.resultados[0]["codigo_error"] == "imagen_invalida"
    assert _claves_fotos(aws) == []


async def test_datos_invalidos_del_levantamiento(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    malo = levantamiento(insp, [])
    malo["estado_ocupacion"] = "OCUPADO"  # exige nombre y contacto del ocupante
    subida_id = await _subir(aws, construir_zip([malo]), cantidad=1)

    assert await _ejecutar(aws, subida_id, FakeServicio()) == "parcial"
    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None and subida.resultados[0]["codigo_error"] == "datos_invalidos"


async def test_sha256_distinto_rechaza_el_zip_completo(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    zip_bytes = construir_zip([levantamiento(insp, [])])
    subida_id = await _subir(aws, zip_bytes, cantidad=1, sha="0" * 64)
    servicio = FakeServicio()

    assert await _ejecutar(aws, subida_id, servicio) == "error"
    assert servicio.recibidos == []
    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None and subida.estado == "error" and subida.error


@pytest.mark.parametrize("nombre", ["../escape.jpg", "/abs.jpg", "a\\b.jpg"])
async def test_ruta_peligrosa_rechaza_el_zip_completo(aws, nombre) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    zip_bytes = construir_zip([levantamiento(insp, [])], {nombre: JPG})
    subida_id = await _subir(aws, zip_bytes, cantidad=1)
    servicio = FakeServicio()

    assert await _ejecutar(aws, subida_id, servicio) == "error"
    assert servicio.recibidos == []


async def test_manifest_con_otra_cantidad_rechaza_el_zip(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    zip_bytes = construir_zip([levantamiento(insp, [])], cantidad_levantamientos=5)
    subida_id = await _subir(aws, zip_bytes, cantidad=1)
    assert await _ejecutar(aws, subida_id, FakeServicio()) == "error"


async def test_archivo_que_no_es_zip(aws) -> None:  # type: ignore[no-untyped-def]
    subida_id = await _subir(aws, b"esto no es un zip", cantidad=1)
    assert await _ejecutar(aws, subida_id, FakeServicio()) == "error"


async def test_reintento_no_duplica_resultados(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    subida_id = await _subir(aws, construir_zip([levantamiento(insp, [])]), cantidad=1)

    await _ejecutar(aws, subida_id, FakeServicio())
    await _ejecutar(aws, subida_id, FakeServicio())  # Batch reintenta el job

    subida = await FakeSubidaStore(aws[0]).obtener(subida_id)
    assert subida is not None and len(subida.resultados) == 1


async def test_subida_de_otro_inspector_no_se_procesa(aws) -> None:  # type: ignore[no-untyped-def]
    insp = str(uuid.uuid4())
    subida_id = await _subir(aws, construir_zip([levantamiento(insp, [])]), cantidad=1)
    settings = aws[0]
    estado = await procesar(
        subida_id,
        "otro@example.com",
        servicio=FakeServicio(),  # type: ignore[arg-type]
        store=FakeSubidaStore(settings),
        s3=SubidaS3(settings),
        settings=settings,
    )
    assert estado == "error"
