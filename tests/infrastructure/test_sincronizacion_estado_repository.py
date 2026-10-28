import uuid
from typing import Any

from app.infrastructure.config.settings import Settings
from app.infrastructure.database.sincronizacion_estado_repository import JobStore, SubidaStore


class RecordingPool:
    def __init__(self, execute_result: str = "UPDATE 1", fetchrow_result: Any = None) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        self._execute_result = execute_result
        self._fetchrow_result = fetchrow_result

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", " ".join(sql.split()), args))
        return self._execute_result

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchrow", " ".join(sql.split()), args))
        return self._fetchrow_result


SETTINGS = Settings(_env_file=None)


async def test_crear_borra_los_vencidos_antes_de_insertar() -> None:
    pool = RecordingPool()
    job_id = str(uuid.uuid4())

    await JobStore(pool, SETTINGS).crear(job_id, "insp@example.com")  # type: ignore[arg-type]

    borrado, insercion = pool.calls
    assert borrado[1] == "DELETE FROM sincronizacion_job WHERE expira_en < NOW()"
    assert insercion[1].startswith("INSERT INTO sincronizacion_job")
    assert insercion[2] == (
        uuid.UUID(job_id),
        "insp@example.com",
        "pendiente",
        SETTINGS.sincronizacion_job_ttl_horas,
    )


async def test_obtener_con_id_que_no_es_uuid_no_consulta_la_base() -> None:
    pool = RecordingPool()

    assert await JobStore(pool, SETTINGS).obtener("no-es-uuid") is None  # type: ignore[arg-type]
    assert await SubidaStore(pool, SETTINGS).obtener("123") is None  # type: ignore[arg-type]
    assert pool.calls == []


async def test_obtener_solo_lee_registros_no_vencidos() -> None:
    pool = RecordingPool()

    assert await JobStore(pool, SETTINGS).obtener(str(uuid.uuid4())) is None  # type: ignore[arg-type]

    assert "expira_en > NOW()" in pool.calls[0][1]


async def test_actualizar_estado_conserva_los_valores_no_enviados() -> None:
    pool = RecordingPool()
    job_id = str(uuid.uuid4())

    await JobStore(pool, SETTINGS).actualizar_estado(job_id, "listo", s3_key="k.zip")  # type: ignore[arg-type]

    sql, args = pool.calls[0][1], pool.calls[0][2]
    assert "error = COALESCE($4, error)" in sql
    assert args == (uuid.UUID(job_id), "listo", "k.zip", None, None)


async def test_reservar_confirmacion_solo_gana_la_primera_vez() -> None:
    subida_id = str(uuid.uuid4())

    gana = SubidaStore(RecordingPool("UPDATE 1"), SETTINGS)  # type: ignore[arg-type]
    pierde = SubidaStore(RecordingPool("UPDATE 0"), SETTINGS)  # type: ignore[arg-type]

    assert await gana.reservar_confirmacion(subida_id) is True
    assert await pierde.reservar_confirmacion(subida_id) is False


async def test_reservar_confirmacion_es_condicional_al_estado() -> None:
    pool = RecordingPool()

    await SubidaStore(pool, SETTINGS).reservar_confirmacion(str(uuid.uuid4()))  # type: ignore[arg-type]

    assert "WHERE subida_id = $1 AND estado = $3" in pool.calls[0][1]
    assert pool.calls[0][2][1:] == ("pendiente", "pendiente_carga")


async def test_agregar_resultado_concatena_al_arreglo_existente() -> None:
    pool = RecordingPool()
    subida_id = str(uuid.uuid4())

    await SubidaStore(pool, SETTINGS).agregar_resultado(subida_id, {"estado": "ok"})  # type: ignore[arg-type]

    assert "resultados = resultados || $2::jsonb" in pool.calls[0][1]
    assert pool.calls[0][2] == (uuid.UUID(subida_id), '[{"estado": "ok"}]')


async def test_obtener_subida_decodifica_los_resultados_json() -> None:
    subida_id = uuid.uuid4()
    fila = {
        "subida_id": subida_id,
        "email_inspector": "insp@example.com",
        "estado": "listo",
        "s3_key": "subidas/x.zip",
        "tamano_bytes": 10,
        "sha256": "a" * 64,
        "cantidad_levantamientos": 1,
        "resultados": '[{"estado": "ok"}]',
        "error": None,
        "batch_job_id": "b1",
    }

    subida = await SubidaStore(RecordingPool(fetchrow_result=fila), SETTINGS).obtener(  # type: ignore[arg-type]
        str(subida_id)
    )

    assert subida is not None
    assert subida.subida_id == str(subida_id)
    assert subida.resultados == [{"estado": "ok"}]
