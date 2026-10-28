import pytest

from app.application.subida_service import (
    SubidaCargaIncompletaError,
    SubidaFueraDeLimiteError,
    SubidaNoEncontradaError,
    SubidaService,
)
from app.infrastructure.clients.aws_sincronizacion import (
    EncolarJobError,
    SincronizacionNoDisponibleError,
)
from app.infrastructure.clients.aws_subida import SubidaJob
from app.infrastructure.config.settings import Settings

SHA = "a" * 64


class FakeStore:
    def __init__(self) -> None:
        self.subidas: dict[str, SubidaJob] = {}

    async def crear(  # type: ignore[no-untyped-def]
        self, subida_id, email, *, s3_key, tamano_bytes, sha256, cantidad_levantamientos
    ) -> None:
        self.subidas[subida_id] = SubidaJob(
            subida_id,
            email,
            "pendiente_carga",
            s3_key,
            tamano_bytes,
            sha256,
            cantidad_levantamientos,
        )

    async def obtener(self, subida_id: str) -> SubidaJob | None:
        return self.subidas.get(subida_id)

    async def reservar_confirmacion(self, subida_id: str) -> bool:
        actual = self.subidas[subida_id]
        if actual.estado != "pendiente_carga":
            return False
        self._cambiar(subida_id, estado="pendiente")
        return True

    async def marcar_confirmada(self, subida_id: str, batch_job_id: str) -> None:
        self._cambiar(subida_id, estado="pendiente", batch_job_id=batch_job_id)

    async def actualizar_estado(self, subida_id, estado, *, error=None, reiniciar_resultados=False):  # type: ignore[no-untyped-def]
        self._cambiar(subida_id, estado=estado, error=error)

    def _cambiar(self, subida_id: str, **cambios) -> None:  # type: ignore[no-untyped-def]
        a = self.subidas[subida_id]
        datos = {**a.__dict__, **{k: v for k, v in cambios.items() if v is not None}}
        self.subidas[subida_id] = SubidaJob(**datos)


class FakeS3:
    def __init__(self, tamano: int | None) -> None:
        self.tamano = tamano

    async def url_carga(self, s3_key: str, tamano_bytes: int) -> str:
        return f"https://s3.test/{s3_key}?firmado&len={tamano_bytes}"

    async def tamano_zip(self, s3_key: str) -> int | None:
        return self.tamano


class FakeSubmitter:
    def __init__(self, falla: Exception | None = None, batch_fallo: bool = False) -> None:
        self.falla = falla
        self.batch_fallo = batch_fallo
        self.llamadas: list[tuple[str, str]] = []

    async def enqueue_subida_job(self, subida_id: str, email: str) -> str:
        if self.falla:
            raise self.falla
        self.llamadas.append((subida_id, email))
        return f"batch-{subida_id}"

    async def job_fallo(self, batch_job_id: str) -> bool:
        return self.batch_fallo


class Reloj:
    def __init__(self) -> None:
        self.ahora = 0.0

    def __call__(self) -> float:
        return self.ahora

    async def dormir(self, segundos: float) -> None:
        self.ahora += segundos


def _servicio(*, tamano=100, habilitada=True, submitter=None, store=None):  # type: ignore[no-untyped-def]
    reloj = Reloj()
    store = store or FakeStore()
    submitter = submitter or FakeSubmitter()
    settings = Settings(sincronizacion_habilitada=habilitada, subida_max_bytes=1000, _env_file=None)
    svc = SubidaService(
        settings,
        store,
        FakeS3(tamano),
        submitter,
        sleep=reloj.dormir,
        reloj=reloj,  # type: ignore[arg-type]
    )
    return svc, store, submitter


async def test_iniciar_registra_y_devuelve_url_prefirmada() -> None:
    svc, store, _ = _servicio()
    creada = await svc.iniciar("insp@x.com", 100, SHA.upper(), 3)
    subida = store.subidas[creada.subida_id]
    assert subida.estado == "pendiente_carga"
    assert subida.sha256 == SHA  # se normaliza a minúsculas
    assert subida.s3_key.startswith("subidas/") and subida.s3_key.endswith(
        f"{creada.subida_id}.zip"
    )
    assert "insp@x.com" not in subida.s3_key
    assert creada.url_carga.startswith("https://s3.test/subidas/")


async def test_iniciar_rechaza_zip_demasiado_grande() -> None:
    svc, store, _ = _servicio()
    with pytest.raises(SubidaFueraDeLimiteError):
        await svc.iniciar("insp@x.com", 1001, SHA, 1)
    assert store.subidas == {}


async def test_deshabilitado_responde_no_disponible() -> None:
    svc, _, _ = _servicio(habilitada=False)
    with pytest.raises(SincronizacionNoDisponibleError):
        await svc.iniciar("insp@x.com", 100, SHA, 1)


async def test_confirmar_encola_y_es_idempotente() -> None:
    svc, store, submitter = _servicio()
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    estado = await svc.confirmar(creada.subida_id, "insp@x.com")
    assert estado.estado == "pendiente"
    assert submitter.llamadas == [(creada.subida_id, "insp@x.com")]
    assert store.subidas[creada.subida_id].batch_job_id == f"batch-{creada.subida_id}"

    await svc.confirmar(creada.subida_id, "insp@x.com")  # reintento de la app
    assert len(submitter.llamadas) == 1


@pytest.mark.parametrize("tamano", [None, 99])
async def test_confirmar_sin_zip_o_con_otro_tamano_responde_conflicto(tamano) -> None:  # type: ignore[no-untyped-def]
    svc, _, submitter = _servicio(tamano=tamano)
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    with pytest.raises(SubidaCargaIncompletaError):
        await svc.confirmar(creada.subida_id, "insp@x.com")
    assert submitter.llamadas == []


async def test_confirmar_ajeno_es_no_encontrada() -> None:
    svc, _, _ = _servicio()
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    with pytest.raises(SubidaNoEncontradaError):
        await svc.confirmar(creada.subida_id, "otro@x.com")


async def test_confirmar_falla_el_encolado_marca_error() -> None:
    svc, store, _ = _servicio(submitter=FakeSubmitter(falla=RuntimeError("batch caído")))
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    with pytest.raises(EncolarJobError):
        await svc.confirmar(creada.subida_id, "insp@x.com")
    assert store.subidas[creada.subida_id].estado == "error"


async def test_consultar_devuelve_resultados_al_terminar() -> None:
    svc, store, _ = _servicio()
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    store._cambiar(creada.subida_id, estado="parcial")
    store._cambiar(creada.subida_id, resultados=[{"id_inspeccion": "i", "exito": False}])
    estado = await svc.consultar(creada.subida_id, "insp@x.com", 5)
    assert estado.estado == "parcial"
    assert estado.resultados == [{"id_inspeccion": "i", "exito": False}]


async def test_consultar_sin_cambio_agota_la_ventana_y_sigue_procesando() -> None:
    svc, _, _ = _servicio()
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    await svc.confirmar(creada.subida_id, "insp@x.com")
    estado = await svc.consultar(creada.subida_id, "insp@x.com", 3)
    assert estado.estado == "pendiente"


async def test_consultar_detecta_job_muerto_en_batch() -> None:
    svc, store, _ = _servicio(submitter=FakeSubmitter(batch_fallo=True))
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    await svc.confirmar(creada.subida_id, "insp@x.com")
    estado = await svc.consultar(creada.subida_id, "insp@x.com", 0)
    assert estado.estado == "error"
    assert store.subidas[creada.subida_id].estado == "error"


async def test_consultar_ajeno_es_no_encontrada() -> None:
    svc, _, _ = _servicio()
    creada = await svc.iniciar("insp@x.com", 100, SHA, 1)
    with pytest.raises(SubidaNoEncontradaError):
        await svc.consultar(creada.subida_id, "otro@x.com", 0)
