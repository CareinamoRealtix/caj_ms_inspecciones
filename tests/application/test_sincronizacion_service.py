import pytest

from app.application.sincronizacion_service import JobNoEncontradoError, SincronizacionService
from app.infrastructure.clients.aws_sincronizacion import (
    EncolarJobError,
    JobSincronizacion,
    SincronizacionNoDisponibleError,
)
from app.infrastructure.config.settings import Settings


class FakeStore:
    def __init__(self) -> None:
        self.jobs: dict[str, JobSincronizacion] = {}
        self.consultas = 0

    async def crear(self, job_id: str, email: str) -> None:
        self.jobs[job_id] = JobSincronizacion(job_id, email, "pendiente")

    async def obtener(self, job_id: str) -> JobSincronizacion | None:
        self.consultas += 1
        return self.jobs.get(job_id)

    async def actualizar_estado(  # type: ignore[no-untyped-def]
        self, job_id, estado, *, s3_key=None, error=None, batch_job_id=None
    ) -> None:
        actual = self.jobs[job_id]
        self.jobs[job_id] = JobSincronizacion(
            job_id,
            actual.email_inspector,
            estado,
            s3_key or actual.s3_key,
            error or actual.error,
            batch_job_id or actual.batch_job_id,
        )


class FakeSubmitter:
    def __init__(self, falla: Exception | None = None, batch_fallo: bool = False) -> None:
        self.falla = falla
        self.batch_fallo = batch_fallo
        self.llamadas: list[tuple[str, str]] = []
        self.origenes: list[tuple[float, float] | None] = []

    async def enqueue_generation_job(
        self, job_id: str, email: str, origen: tuple[float, float] | None = None
    ) -> str:
        if self.falla:
            raise self.falla
        self.llamadas.append((job_id, email))
        self.origenes.append(origen)
        return f"batch-{job_id}"

    async def job_fallo(self, batch_job_id: str) -> bool:
        return self.batch_fallo


class FakeSigner:
    def firmar(self, s3_key: str) -> str:
        return f"https://cdn.test/{s3_key}?firmado"


class Reloj:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, segundos: float) -> None:
        self.t += segundos


def _servicio(store=None, submitter=None, habilitada=True, reloj=None):  # type: ignore[no-untyped-def]
    reloj = reloj or Reloj()
    settings = Settings(sincronizacion_habilitada=habilitada, _env_file=None)
    svc = SincronizacionService(
        settings,
        store or FakeStore(),  # type: ignore[arg-type]
        submitter or FakeSubmitter(),  # type: ignore[arg-type]
        FakeSigner(),  # type: ignore[arg-type]
        sleep=reloj.sleep,
        reloj=reloj,
    )
    return svc, reloj


async def test_iniciar_registra_job_y_lo_encola() -> None:
    store, submitter = FakeStore(), FakeSubmitter()
    svc, _ = _servicio(store, submitter)

    job_id = await svc.iniciar("insp@example.com")

    assert store.jobs[job_id].estado == "pendiente"
    assert submitter.llamadas == [(job_id, "insp@example.com")]
    assert submitter.origenes == [None]


async def test_iniciar_con_origen_lo_pasa_al_job_sin_guardarlo() -> None:
    store, submitter = FakeStore(), FakeSubmitter()
    svc, _ = _servicio(store, submitter)

    job_id = await svc.iniciar("insp@example.com", (8.98, -79.53))

    assert submitter.origenes == [(8.98, -79.53)]
    assert "8.98" not in repr(store.jobs[job_id])


async def test_iniciar_deshabilitada_no_toca_aws() -> None:
    store, submitter = FakeStore(), FakeSubmitter()
    svc, _ = _servicio(store, submitter, habilitada=False)

    with pytest.raises(SincronizacionNoDisponibleError):
        await svc.iniciar("insp@example.com")

    assert store.jobs == {}
    assert submitter.llamadas == []


async def test_iniciar_si_falla_el_encolado_marca_error() -> None:
    store = FakeStore()
    svc, _ = _servicio(store, FakeSubmitter(falla=RuntimeError("boom")))

    with pytest.raises(EncolarJobError):
        await svc.iniciar("insp@example.com")

    (job,) = store.jobs.values()
    assert job.estado == "error"


async def test_consultar_listo_devuelve_url_firmada() -> None:
    store = FakeStore()
    store.jobs["j1"] = JobSincronizacion(
        "j1", "insp@example.com", "listo", s3_key="sincronizacion/x.zip"
    )
    svc, _ = _servicio(store)

    estado = await svc.consultar("j1", "insp@example.com", espera=25)

    assert estado.estado == "listo"
    assert estado.url_firmada == "https://cdn.test/sincronizacion/x.zip?firmado"


async def test_consultar_espera_hasta_que_termina() -> None:
    store = FakeStore()
    store.jobs["j1"] = JobSincronizacion("j1", "a@b.c", "procesando")
    svc, reloj = _servicio(store)

    original_sleep = reloj.sleep

    async def sleep_y_termina(segundos: float) -> None:
        await original_sleep(segundos)
        if reloj.t >= 3:
            store.jobs["j1"] = JobSincronizacion("j1", "a@b.c", "listo", s3_key="k.zip")

    svc._sleep = sleep_y_termina  # type: ignore[assignment]
    estado = await svc.consultar("j1", "a@b.c", espera=25)

    assert estado.estado == "listo"
    assert reloj.t < 25


async def test_consultar_agota_la_ventana_y_devuelve_procesando() -> None:
    store = FakeStore()
    store.jobs["j1"] = JobSincronizacion("j1", "a@b.c", "procesando")
    svc, reloj = _servicio(store)

    estado = await svc.consultar("j1", "a@b.c", espera=5)

    assert estado.estado == "procesando"
    assert estado.url_firmada is None
    assert 5 <= reloj.t < 8


async def test_consultar_tope_de_espera_del_servidor() -> None:
    store = FakeStore()
    store.jobs["j1"] = JobSincronizacion("j1", "a@b.c", "procesando")
    svc, reloj = _servicio(store)

    await svc.consultar("j1", "a@b.c", espera=50)

    assert reloj.t < 25 + 2


async def test_consultar_error_devuelve_mensaje() -> None:
    store = FakeStore()
    store.jobs["j1"] = JobSincronizacion("j1", "a@b.c", "error", error="falló")
    svc, _ = _servicio(store)

    estado = await svc.consultar("j1", "a@b.c", espera=0)

    assert (estado.estado, estado.error) == ("error", "falló")


async def test_consultar_job_de_otro_inspector_es_no_encontrado() -> None:
    store = FakeStore()
    store.jobs["j1"] = JobSincronizacion("j1", "otro@b.c", "listo", s3_key="k.zip")
    svc, _ = _servicio(store)

    with pytest.raises(JobNoEncontradoError):
        await svc.consultar("j1", "a@b.c", espera=0)


async def test_consultar_job_inexistente() -> None:
    svc, _ = _servicio()

    with pytest.raises(JobNoEncontradoError):
        await svc.consultar("nope", "a@b.c", espera=0)


async def test_iniciar_guarda_el_id_de_batch() -> None:
    store = FakeStore()
    svc, _ = _servicio(store)

    job_id = await svc.iniciar("insp@example.com")

    assert store.jobs[job_id].batch_job_id == f"batch-{job_id}"


async def test_consultar_detecta_job_fallido_en_batch_y_marca_error() -> None:
    store = FakeStore()
    store.jobs["j1"] = JobSincronizacion("j1", "a@b.c", "procesando", batch_job_id="b1")
    svc, _ = _servicio(store, FakeSubmitter(batch_fallo=True))

    estado = await svc.consultar("j1", "a@b.c", espera=2)

    assert estado.estado == "error"
    assert store.jobs["j1"].estado == "error"
