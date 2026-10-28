import json
import uuid
from collections import Counter
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.infrastructure.database.inspeccion_repository import InspeccionRepository
from app.presentation.api.schemas.inspecciones import (
    BienFormularioBatchRequest,
    DetalleInspeccionResponse,
    FormularioCreateRequest,
    FormularioDetailResponse,
)

_INSPECCION_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


class InsertRecordingPool:
    def __init__(self) -> None:
        self.sql = ""
        self.args: tuple[Any, ...] = ()
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> "InsertRecordingPool":
        return self

    def transaction(self) -> "InsertRecordingPool":
        return self

    async def __aenter__(self) -> "InsertRecordingPool":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, int]:
        self.sql = " ".join(sql.split())
        self.args = args
        return {"numero_inspeccion": 42}

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.sql = " ".join(sql.split())
        self.args = args
        return []

    async def fetchval(self, sql: str, *args: Any) -> int:
        self.sql = " ".join(sql.split())
        self.args = args
        return 90

    async def execute(self, sql: str, *args: Any) -> None:
        self.execute_calls.append((" ".join(sql.split()), args))
        return None


def _request_data() -> dict[str, Any]:
    return {
        "id_bien_inventario": uuid.UUID("00000000-0000-4000-8000-000000000002"),
        "numero_finca": "FINCA-001",
        "ruta_id": uuid.UUID("00000000-0000-4000-8000-000000000101"),
        "ruta_nombre": "Ruta Centro",
        "id_tipo_inspeccion": 1,
        "descripcion_tipo": None,
        "email_inspector": "inspector@example.com",
        "id_periodicidad": 6,
        "fecha_programada": date(2026, 9, 1),
    }


def test_create_request_requires_route_fields() -> None:
    data = _request_data()
    data.pop("ruta_id")

    with pytest.raises(ValidationError):
        FormularioCreateRequest(**data)


def test_create_request_rejects_blank_route_fields() -> None:
    data = _request_data()
    data["ruta_nombre"] = "   "

    with pytest.raises(ValidationError):
        FormularioCreateRequest(**data)


def test_inspection_requests_accept_property_numbers_longer_than_fifteen_characters() -> None:
    numero_finca = "FINCA-" + ("1234567890" * 20)
    data = _request_data()
    data["numero_finca"] = numero_finca

    request = FormularioCreateRequest(**data)
    batch_item = BienFormularioBatchRequest(
        id_bien_inventario=data["id_bien_inventario"],
        numero_finca=numero_finca,
    )

    assert request.numero_finca == numero_finca
    assert batch_item.numero_finca == numero_finca


async def test_insert_persists_route_fields() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    data = _request_data()

    numero = await repository.insert_inspeccion(
        id_inspeccion=_INSPECCION_ID,
        id_bien_inventario=data["id_bien_inventario"],
        numero_finca=data["numero_finca"],
        ruta_id=data["ruta_id"],
        ruta_nombre=data["ruta_nombre"],
        id_tipo_inspeccion=data["id_tipo_inspeccion"],
        id_periodicidad=data["id_periodicidad"],
        email_inspector=data["email_inspector"],
        fecha_programada=data["fecha_programada"],
        fecha_vencimiento=None,
        descripcion_tipo=data["descripcion_tipo"],
        creado_por="creator@example.com",
    )

    assert numero == 42
    assert "numero_finca, ruta_id, ruta_nombre" in pool.sql
    assert "id_periodicidad" in pool.sql
    assert "requiere_programacion_automatica" not in pool.sql
    assert "fecha_vencimiento" in pool.sql
    assert "$12" in pool.sql
    assert "fecha_vencimiento, activa" in pool.sql
    assert "id_inspector" not in pool.sql
    assert pool.args[3:5] == (
        uuid.UUID("00000000-0000-4000-8000-000000000101"),
        "Ruta Centro",
    )
    assert pool.args[10] is None
    assert len(pool.execute_calls) == 1
    ruta_sql, ruta_args = pool.execute_calls[0]
    assert "ON CONFLICT (id_bien_inventario, numero_finca) DO UPDATE" in ruta_sql
    assert ruta_args == (
        data["id_bien_inventario"],
        data["ruta_id"],
        data["numero_finca"],
    )


async def test_upsert_bien_inventario_ruta_keys_by_bien_and_finca() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    bien_id = uuid.UUID("00000000-0000-4000-8000-000000000002")
    ruta_id = uuid.UUID("00000000-0000-4000-8000-000000000101")

    await repository.upsert_bien_inventario_ruta(
        id_bien_inventario=bien_id, id_ruta=ruta_id, numero_finca="FINCA-002"
    )

    assert len(pool.execute_calls) == 1
    sql, args = pool.execute_calls[0]
    assert "ON CONFLICT (id_bien_inventario, numero_finca) DO UPDATE" in sql
    assert "numero_finca = EXCLUDED.numero_finca" not in sql
    assert args == (bien_id, ruta_id, "FINCA-002")


async def test_bien_inventario_rutas_lookup_joins_route_names() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    bien_id = uuid.UUID("00000000-0000-4000-8000-000000000002")

    await repository.get_bien_inventario_rutas_for_bienes([bien_id])

    assert "FROM inspecciones.bien_inventario_ruta bir" in pool.sql
    assert "JOIN inspecciones.ruta r ON r.id = bir.id_ruta" in pool.sql
    assert "bir.id_bien_inventario = ANY($1::uuid[])" in pool.sql
    assert pool.args == ([bien_id],)


async def test_batch_insert_uses_one_atomic_statement_with_all_bienes() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    first_id = uuid.UUID("00000000-0000-4000-8000-000000000011")
    second_id = uuid.UUID("00000000-0000-4000-8000-000000000012")
    common = _request_data()
    inspecciones = [
        {
            **common,
            "id_inspeccion": first_id,
            "fecha_vencimiento": None,
        },
        {
            **common,
            "id_inspeccion": second_id,
            "id_bien_inventario": uuid.UUID("00000000-0000-4000-8000-000000000003"),
            "numero_finca": "FINCA-002",
            "fecha_vencimiento": None,
        },
    ]

    await repository.insert_inspecciones_batch(
        inspecciones=inspecciones,
        creado_por="creator@example.com",
    )

    assert pool.sql.count("INSERT INTO inspecciones.inspeccion") == 1
    assert "FROM UNNEST(" in pool.sql
    assert "RETURNING id_inspeccion, numero_inspeccion" in pool.sql
    assert pool.args[0] == [first_id, second_id]
    assert pool.args[2] == ["FINCA-001", "FINCA-002"]
    assert pool.args[6] == [6, 6]
    assert pool.args[10] == [None, None]
    assert pool.args[11] == "creator@example.com"


async def test_form_catalog_reads_routes_from_local_catalog_table() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_rutas()

    assert pool.sql == (
        "SELECT id, codigo, nombre FROM inspecciones.ruta ORDER BY nombre, codigo"
    )


async def test_periodicity_days_are_read_by_id() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    days = await repository.get_periodicidad_dias(6)

    assert days == 90
    assert "FROM inspecciones.periodicidad WHERE id_periodicidad = $1" in pool.sql
    assert pool.args == (6,)


async def test_update_persists_inspector_and_pending_expiration() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    data = _request_data()

    await repository.update_inspeccion(
        id_inspeccion=_INSPECCION_ID,
        ruta_id=data["ruta_id"],
        ruta_nombre=data["ruta_nombre"],
        id_tipo_inspeccion=data["id_tipo_inspeccion"],
        id_periodicidad=data["id_periodicidad"],
        email_inspector=data["email_inspector"],
        fecha_programada=data["fecha_programada"],
        fecha_vencimiento=None,
        descripcion_tipo=data["descripcion_tipo"],
        modificado_por="editor@example.com",
    )

    assert "id_periodicidad = $4" in pool.sql
    assert "email_inspector = $5" in pool.sql
    assert "fecha_vencimiento = $8" in pool.sql
    assert "activa = TRUE" in pool.sql
    assert "WHERE id_inspeccion = $10" in pool.sql
    assert "requiere_programacion_automatica" not in pool.sql
    assert "id_inspector" not in pool.sql


class FinalizarLevantamientoConnection:
    """Fake de conexión que devuelve, en orden, un fetchrow canned por llamada."""

    def __init__(self, fetchrow_returns: list[dict[str, Any] | None]) -> None:
        self._fetchrow_returns = list(fetchrow_returns)
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> "FinalizarLevantamientoConnection":
        return self

    def transaction(self) -> "FinalizarLevantamientoConnection":
        return self

    async def __aenter__(self) -> "FinalizarLevantamientoConnection":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((" ".join(sql.split()), args))
        return self._fetchrow_returns.pop(0)

    async def execute(self, sql: str, *args: Any) -> None:
        self.execute_calls.append((" ".join(sql.split()), args))


def _levantamiento_data() -> dict[str, Any]:
    return {
        "condicion_bien": "REGULAR",
        "estado_ocupacion": "DESOCUPADO",
    }


async def test_finalizing_levantamiento_locks_row_and_calculates_expiration() -> None:
    id_levantamiento = uuid.uuid4()
    id_bien_inventario = uuid.uuid4()
    connection = FinalizarLevantamientoConnection(
        [
            {  # SELECT ... FOR UPDATE
                "fecha_realizada": None,
                "numero_inspeccion": 42,
                "id_bien_inventario": id_bien_inventario,
            },
            None,  # sin operación previa con ese id_operacion
            {"id_levantamiento": id_levantamiento},  # INSERT levantamiento
        ]
    )
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]
    fecha_realizada = date(2026, 9, 3)

    resultado = await repository.finalizar_levantamiento(
        id_inspeccion=_INSPECCION_ID,
        id_operacion=uuid.uuid4(),
        contenido_hash="hash-1",
        data=_levantamiento_data(),
        fecha_levantamiento=fecha_realizada,
        creado_por="inspector@example.com",
    )

    assert resultado.estado == "creado"
    assert resultado.id_levantamiento == id_levantamiento
    assert resultado.numero_inspeccion == 42
    assert resultado.id_bien_inventario == id_bien_inventario
    assert "FOR UPDATE" in connection.fetchrow_calls[0][0]
    assert "ON CONFLICT (id_inspeccion) DO NOTHING" in connection.fetchrow_calls[2][0]

    update_sql = connection.execute_calls[0][0]
    assert "activa = FALSE" in update_sql
    assert "$1::date + (" in update_sql
    assert "p.id_periodicidad = i.id_periodicidad" in update_sql
    assert connection.execute_calls[0][1][0] == fecha_realizada

    assert "INSERT INTO inspecciones.levantamiento_operacion" in connection.execute_calls[1][0]


async def test_finalizar_levantamiento_inserta_fotografias_por_url() -> None:
    id_levantamiento = uuid.uuid4()
    connection = FinalizarLevantamientoConnection(
        [
            {
                "fecha_realizada": None,
                "numero_inspeccion": 42,
                "id_bien_inventario": uuid.uuid4(),
            },
            None,
            {"id_levantamiento": id_levantamiento},
        ]
    )
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]

    resultado = await repository.finalizar_levantamiento(
        id_inspeccion=_INSPECCION_ID,
        id_operacion=uuid.uuid4(),
        contenido_hash="hash-1",
        data=_levantamiento_data(),
        fecha_levantamiento=date(2026, 9, 3),
        creado_por="inspector@example.com",
        fotografias=[
            {"url": "https://via.placeholder.com/300", "es_foto_principal": True},
            {"url": "https://via.placeholder.com/400", "nombre_archivo": "fachada.jpg"},
        ],
    )

    assert resultado.estado == "creado"
    foto_calls = [c for c in connection.execute_calls if "inspeccion_fotografia" in c[0]]
    assert len(foto_calls) == 2

    primera_sql, primeros_args = foto_calls[0]
    assert "INSERT INTO inspecciones.inspeccion_fotografia" in primera_sql
    assert primeros_args == (
        id_levantamiento,
        "https://via.placeholder.com/300",
        None,
        False,
        True,
        0,
    )

    _, segundos_args = foto_calls[1]
    assert segundos_args == (
        id_levantamiento,
        "https://via.placeholder.com/400",
        "fachada.jpg",
        False,
        False,
        1,
    )


async def test_finalizar_levantamiento_replays_identical_retry() -> None:
    respuesta = {
        "id_levantamiento": str(uuid.uuid4()),
        "id_inspeccion": str(_INSPECCION_ID),
        "estado_inspeccion": "Finalizada",
        "mensaje": "Levantamiento finalizado correctamente",
    }
    connection = FinalizarLevantamientoConnection(
        [
            {"fecha_realizada": None},
            {
                "id_inspeccion": _INSPECCION_ID,
                "contenido_hash": "hash-1",
                "respuesta": json.dumps(respuesta),
            },
        ]
    )
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]

    resultado = await repository.finalizar_levantamiento(
        id_inspeccion=_INSPECCION_ID,
        id_operacion=uuid.uuid4(),
        contenido_hash="hash-1",
        data=_levantamiento_data(),
        fecha_levantamiento=date(2026, 9, 3),
        creado_por="inspector@example.com",
    )

    assert resultado.estado == "repetido"
    assert resultado.respuesta_previa == respuesta
    assert connection.execute_calls == []


async def test_finalizar_levantamiento_conflicto_por_contenido_distinto() -> None:
    connection = FinalizarLevantamientoConnection(
        [
            {"fecha_realizada": None},
            {"id_inspeccion": _INSPECCION_ID, "contenido_hash": "hash-otro", "respuesta": "{}"},
        ]
    )
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]

    resultado = await repository.finalizar_levantamiento(
        id_inspeccion=_INSPECCION_ID,
        id_operacion=uuid.uuid4(),
        contenido_hash="hash-1",
        data=_levantamiento_data(),
        fecha_levantamiento=date(2026, 9, 3),
        creado_por="inspector@example.com",
    )

    assert resultado.estado == "conflicto_contenido"
    assert connection.execute_calls == []


async def test_finalizar_levantamiento_rechaza_id_operacion_de_otra_inspeccion() -> None:
    """id_operacion es la PRIMARY KEY de levantamiento_operacion (global, no por inspección).

    Reproduce el bug real: un cliente reutiliza el mismo id_operacion para finalizar una
    inspección distinta a la original. Antes del fix, si el contenido coincidía por
    casualidad (mismo body), el código devolvía "repetido" con la respuesta de la OTRA
    inspección sin haber tocado la fila bloqueada de la inspección actual — pareciendo un
    200 exitoso que en realidad no finalizó nada."""
    otra_inspeccion_id = uuid.uuid4()
    connection = FinalizarLevantamientoConnection(
        [
            {"fecha_realizada": None},
            {
                "id_inspeccion": otra_inspeccion_id,
                "contenido_hash": "hash-1",
                "respuesta": "{}",
            },
        ]
    )
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]

    resultado = await repository.finalizar_levantamiento(
        id_inspeccion=_INSPECCION_ID,
        id_operacion=uuid.uuid4(),
        contenido_hash="hash-1",
        data=_levantamiento_data(),
        fecha_levantamiento=date(2026, 9, 3),
        creado_por="inspector@example.com",
    )

    assert resultado.estado == "operacion_de_otra_inspeccion"
    assert connection.execute_calls == []


async def test_finalizar_levantamiento_ya_finalizada_por_otra_operacion() -> None:
    connection = FinalizarLevantamientoConnection(
        [
            {"fecha_realizada": date(2026, 1, 1)},
            None,
        ]
    )
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]

    resultado = await repository.finalizar_levantamiento(
        id_inspeccion=_INSPECCION_ID,
        id_operacion=uuid.uuid4(),
        contenido_hash="hash-1",
        data=_levantamiento_data(),
        fecha_levantamiento=date(2026, 9, 3),
        creado_por="inspector@example.com",
    )

    assert resultado.estado == "ya_finalizada"
    assert connection.execute_calls == []


async def test_finalizar_levantamiento_inspeccion_no_encontrada() -> None:
    connection = FinalizarLevantamientoConnection([None])
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]

    resultado = await repository.finalizar_levantamiento(
        id_inspeccion=_INSPECCION_ID,
        id_operacion=uuid.uuid4(),
        contenido_hash="hash-1",
        data=_levantamiento_data(),
        fecha_levantamiento=date(2026, 9, 3),
        creado_por="inspector@example.com",
    )

    assert resultado.estado == "no_encontrada"
    assert len(connection.fetchrow_calls) == 1


async def test_update_fotografias_clears_previous_principal_before_setting_the_new_one() -> None:
    """Reproduce el UniqueViolationError de uq_foto_principal al intercambiar la principal.

    Si la fila que hoy es principal no se limpia antes del UPDATE por foto, dos filas
    quedan con es_foto_principal = TRUE al mismo tiempo dentro de la transacción.
    """
    connection = FinalizarLevantamientoConnection([])
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]
    nueva_principal = uuid.uuid4()

    await repository.update_fotografias(
        _INSPECCION_ID,
        [
            {
                "id_fotografia": nueva_principal,
                "es_visible_geovisor": False,
                "es_foto_principal": True,
            }
        ],
    )

    assert len(connection.execute_calls) == 2
    clear_sql, clear_args = connection.execute_calls[0]
    assert "SET es_foto_principal = FALSE" in clear_sql
    assert "f.es_foto_principal = TRUE" in clear_sql
    assert "f.id_fotografia != $2" in clear_sql
    assert clear_args == (_INSPECCION_ID, nueva_principal)

    update_sql, update_args = connection.execute_calls[1]
    assert "SET es_visible_geovisor = $1" in update_sql
    assert update_args == (False, True, _INSPECCION_ID, nueva_principal)


async def test_update_fotografias_skips_clear_step_without_a_new_principal() -> None:
    connection = FinalizarLevantamientoConnection([])
    repository = InspeccionRepository(connection)  # type: ignore[arg-type]

    await repository.update_fotografias(
        _INSPECCION_ID,
        [
            {
                "id_fotografia": uuid.uuid4(),
                "es_visible_geovisor": True,
                "es_foto_principal": False,
            }
        ],
    )

    assert len(connection.execute_calls) == 1
    assert "SET es_visible_geovisor = $1" in connection.execute_calls[0][0]


async def test_get_levantamiento_opciones_activas_query() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_levantamiento_opciones_activas()

    assert "FROM inspecciones.levantamiento_opcion" in pool.sql
    assert "UNION ALL" in pool.sql
    assert "tipo_servicio AS tipo_catalogo" in pool.sql
    assert "FROM inspecciones.servicio" in pool.sql
    assert pool.sql.count("WHERE es_activo") == 2
    assert "ORDER BY tipo_catalogo, orden, nombre" in pool.sql


async def test_active_inspeccion_lookup_scopes_by_bien_and_finca() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    bien_id = uuid.UUID("00000000-0000-4000-8000-000000000002")

    await repository.get_active_inspeccion_by_bien_finca(bien_id, " FINCA-001 ")

    assert "id_bien_inventario = $1" in pool.sql
    assert "numero_finca = $2" in pool.sql
    assert "activa = TRUE" in pool.sql
    assert "es_activo" not in pool.sql
    assert pool.args == (bien_id, "FINCA-001")


def test_bien_ruta_key_migration_scopes_uniqueness_by_bien_and_finca() -> None:
    migration = Path(
        "migrations/versions/20260905_0026_compose_bien_ruta_key_with_finca.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260905_0025"' in migration
    assert "DROP CONSTRAINT bien_inventario_ruta_pkey" in upgrade
    assert (
        "ADD CONSTRAINT uq_bien_inventario_ruta_bien_finca "
        "UNIQUE (id_bien_inventario, numero_finca)" in upgrade
        or "UNIQUE (id_bien_inventario, numero_finca)" in upgrade
    )
    assert "ADD CONSTRAINT bien_inventario_ruta_pkey" in downgrade
    assert "PRIMARY KEY (id_bien_inventario)" in downgrade


def test_deactivate_completed_inspections_migration_backfills_and_enforces_uniqueness() -> None:
    migration = Path(
        "migrations/versions/20260905_0025_deactivate_completed_inspections.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260903_0024"' in migration
    assert "SET es_activo = FALSE" in upgrade
    assert "WHERE fecha_realizada IS NOT NULL" in upgrade
    assert "AND es_activo = TRUE" in upgrade
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_inspeccion_activa_por_bien_finca" in upgrade
    assert "WHERE es_activo = true" in upgrade or "WHERE es_activo = TRUE" in upgrade
    assert "DROP INDEX IF EXISTS inspecciones.ux_inspeccion_activa_por_bien_finca" in downgrade


def test_activa_migration_backfills_and_enforces_lifecycle_rules() -> None:
    migration = Path(
        "migrations/versions/20260907_0029_add_activa_source_of_truth.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260907_0028"' in migration
    assert "ADD COLUMN activa BOOLEAN" in upgrade
    assert "SET activa = (fecha_realizada IS NULL)" in upgrade
    assert "ALTER COLUMN activa SET NOT NULL" in upgrade
    assert "WHERE activa = TRUE" in upgrade
    assert "ck_inspeccion_activa_fecha_realizada" in upgrade
    assert "DROP COLUMN activa" in downgrade


async def test_form_detail_joins_persisted_periodicity_catalog() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inspeccion_by_id(_INSPECCION_ID)

    assert "i.id_periodicidad" in pool.sql
    assert "p.nombre AS periodicidad" in pool.sql
    assert "p.dias_vigencia" in pool.sql
    assert "LEFT JOIN inspecciones.periodicidad p" in pool.sql


async def test_get_detalle_joins_inventory_view_for_address_fields() -> None:
    pool = InsertRecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_detalle(_INSPECCION_ID)

    assert "LEFT JOIN inspecciones.v_consulta_inventario v" in pool.sql
    assert "ON v.id_bien_inventario = i.id_bien_inventario" in pool.sql
    assert "v.provincia" in pool.sql
    assert "v.distrito" in pool.sql
    assert "v.corregimiento" in pool.sql
    assert "v.barriada_sector" in pool.sql
    assert "v.direccion" in pool.sql
    assert "v.numero_lote" in pool.sql


def test_route_migration_enforces_required_non_blank_columns() -> None:
    migration = Path(
        "migrations/versions/20260827_0005_add_ruta_to_inspeccion.py"
    ).read_text(encoding="utf-8")

    assert "ruta_id VARCHAR(100)" in migration
    assert "ruta_nombre VARCHAR(255)" in migration
    assert "ALTER COLUMN ruta_id SET NOT NULL" in migration
    assert "ALTER COLUMN ruta_nombre SET NOT NULL" in migration
    assert "chk_inspeccion_ruta_no_vacia" in migration


def test_expiration_migration_uses_calendar_days_and_drops_old_column() -> None:
    migration = Path(
        "migrations/versions/20260827_0006_replace_next_schedule_with_expiration.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert "WHEN 'Trimestral' THEN 90" in upgrade
    assert "ADD COLUMN fecha_vencimiento DATE" in upgrade
    assert "DROP COLUMN fecha_siguiente_programacion" in upgrade
    assert "dias_vigencia" in upgrade


def test_parent_inspection_migration_drops_obsolete_relationship() -> None:
    migration = Path(
        "migrations/versions/20260829_0009_drop_inspeccion_parent.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert 'down_revision: str | None = "20260827_0008"' in migration
    assert "DROP COLUMN IF EXISTS id_inspeccion_padre" in upgrade


def test_automatic_scheduling_migration_clears_expiration_and_drops_flag() -> None:
    migration = Path(
        "migrations/versions/20260829_0014_drop_automatic_scheduling.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert 'down_revision: str | None = "20260829_0013"' in migration
    assert "DROP CONSTRAINT IF EXISTS chk_inspeccion_periodicidad_vencimiento" in upgrade
    assert "SET fecha_vencimiento = NULL" in upgrade
    assert "DROP COLUMN IF EXISTS requiere_programacion_automatica" in upgrade
    assert "TODO: cálculo pendiente de definición" in upgrade


def test_api_responses_do_not_expose_parent_inspection() -> None:
    assert "id_inspeccion_padre" not in FormularioDetailResponse.model_fields
    assert "id_inspeccion_padre" not in DetalleInspeccionResponse.model_fields


def test_ruta_migration_creates_two_column_catalog() -> None:
    migration = Path(
        "migrations/versions/20260829_0010_create_rutas_table.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert 'down_revision: str | None = "20260829_0009"' in migration
    assert "CREATE TABLE inspecciones.ruta" in upgrade
    assert "id     VARCHAR(100) PRIMARY KEY" in upgrade
    assert "nombre VARCHAR(255) NOT NULL UNIQUE" in upgrade
    assert "DROP TABLE IF EXISTS inspecciones.ruta" in migration


def test_inspeccion_periodicidad_migration_drops_foreign_key_column() -> None:
    migration = Path(
        "migrations/versions/20260829_0012_drop_inspeccion_periodicidad.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert 'down_revision: str | None = "20260829_0011"' in migration
    assert "DROP COLUMN IF EXISTS id_periodicidad" in upgrade
    assert "inspeccion_id_periodicidad_fkey" in upgrade
    assert "AND id_periodicidad IS NOT NULL" not in upgrade


def test_inspection_periodicity_is_restored_and_backfilled() -> None:
    migration = Path(
        "migrations/versions/20260901_0022_restore_inspection_periodicity.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert 'down_revision: str | None = "20260831_0021"' in migration
    assert "ADD COLUMN id_periodicidad INTEGER" in upgrade
    assert "FOREIGN KEY (id_periodicidad)" in upgrade
    assert "i.fecha_vencimiento - i.fecha_programada = p.dias_vigencia" in upgrade
    assert "CREATE INDEX idx_inspeccion_periodicidad" in upgrade


def test_numero_finca_migration_removes_length_limit_from_local_tables() -> None:
    migration = Path("migrations/versions/20260901_0023_expand_numero_finca.py").read_text(
        encoding="utf-8"
    )
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260901_0022"' in migration
    assert "ALTER TABLE inspecciones.inspeccion" in upgrade
    assert "ALTER TABLE inspecciones.bien_inventario_ruta" in upgrade
    assert upgrade.count("ALTER COLUMN numero_finca TYPE TEXT") == 2
    assert downgrade.count("ALTER COLUMN numero_finca TYPE VARCHAR(15)") == 2


def test_inspector_id_migration_preserves_historical_rows() -> None:
    migration = Path(
        "migrations/versions/20260830_0015_add_inspector_id.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert 'down_revision: str | None = "20260829_0014"' in migration
    assert "ADD COLUMN id_inspector UUID" in upgrade
    assert "ADD COLUMN id_inspector UUID NOT NULL" not in upgrade
    assert "idx_inspeccion_inspector" in upgrade
    assert "Fecha programada más los días calendario" in upgrade


def test_test_routes_migration_is_idempotent_and_reversible() -> None:
    migration = Path(
        "migrations/versions/20260830_0016_seed_test_routes.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260830_0015"' in migration
    assert "INSERT INTO inspecciones.ruta" in upgrade
    assert "('RUTA-001', 'Ruta Centro')" in upgrade
    assert "('RUTA-002', 'Ruta Este')" in upgrade
    assert "('RUTA-003', 'Ruta Oeste')" in upgrade
    assert "ON CONFLICT DO NOTHING" in upgrade
    assert "DELETE FROM inspecciones.ruta" in downgrade


def test_inventory_route_table_adds_property_number_and_route_index() -> None:
    create_migration = Path(
        "migrations/versions/20260829_0011_create_bien_inventario_ruta.py"
    ).read_text(encoding="utf-8")
    migration = Path(
        "migrations/versions/20260831_0017_add_numero_finca_to_bien_ruta.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert "CREATE TABLE inspecciones.bien_inventario_ruta" in create_migration
    assert "REFERENCES inspecciones.ruta(id) ON DELETE RESTRICT" in create_migration
    assert 'down_revision: str | None = "20260830_0016"' in migration
    assert "ADD COLUMN numero_finca VARCHAR(15)" in upgrade
    assert "i.id_bien_inventario = bir.id_bien_inventario" in upgrade
    assert "ALTER COLUMN numero_finca SET NOT NULL" in upgrade
    assert "chk_bien_inventario_ruta_finca_no_vacia" in upgrade
    assert "CREATE INDEX idx_bien_inventario_ruta_ruta" in upgrade
    assert "DROP COLUMN IF EXISTS numero_finca" in downgrade


def test_additional_test_routes_migration_is_idempotent_and_reversible() -> None:
    migration = Path(
        "migrations/versions/20260831_0018_seed_additional_test_routes.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260831_0017"' in migration
    assert "INSERT INTO inspecciones.ruta" in upgrade
    assert "('RUTA-004', 'Ruta Norte')" in upgrade
    assert "('RUTA-005', 'Ruta Sur')" in upgrade
    assert "('RUTA-006', 'Ruta Metropolitana')" in upgrade
    assert "ON CONFLICT DO NOTHING" in upgrade
    assert "DELETE FROM inspecciones.ruta" in downgrade


def _load_seed_inventory_route_assignments_migration() -> Any:
    path = Path(
        "migrations/versions/20260831_0019_seed_inventory_route_assignments.py"
    )
    spec = spec_from_file_location("seed_inventory_route_assignments", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_inventory_route_seed_skips_gracefully_without_the_historical_export() -> None:
    """The one-time inventory export this migration seeded from is no longer shipped with the
    repo; `_load_assignments` must return an empty list instead of raising, so `upgrade()`/
    `downgrade()` can still run (only the nullability change persists, no rows are seeded)."""
    migration = _load_seed_inventory_route_assignments_migration()

    assert not migration._CSV_PATH.exists()
    assert migration._load_assignments() == []
    assert migration.down_revision == "20260831_0018"


def test_inventory_route_seed_distributes_assignments_round_robin_when_export_is_present(
    tmp_path: Any,
) -> None:
    migration = _load_seed_inventory_route_assignments_migration()
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "id_bien_inventario,numeros_finca\n"
        "6ba7b810-48ee-41e5-8333-b359149689fb,{}\n"
        "6ba7b810-f2c8-451e-9e71-ee8c7bdcd441,{1,2}\n",
        encoding="ascii",
    )
    migration._CSV_PATH = csv_path

    assignments = migration._load_assignments()
    route_counts = Counter(row["id_ruta"] for row in assignments)

    assert len(assignments) == 2
    assert route_counts == {"RUTA-001": 1, "RUTA-002": 1}
    assert assignments[0] == {
        "id_bien_inventario": "6ba7b810-48ee-41e5-8333-b359149689fb",
        "id_ruta": "RUTA-001",
        "numero_finca": None,
    }
    assert assignments[1] == {
        "id_bien_inventario": "6ba7b810-f2c8-451e-9e71-ee8c7bdcd441",
        "id_ruta": "RUTA-002",
        "numero_finca": "1",
    }


def test_route_uuid_migration_preserves_codes_and_updates_assignment_fk() -> None:
    migration = Path(
        "migrations/versions/20260831_0020_use_uuid_route_primary_key.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260831_0019"' in migration
    assert "RENAME COLUMN id TO codigo" in upgrade
    assert "ADD COLUMN id UUID NOT NULL DEFAULT gen_random_uuid()" in upgrade
    assert "WHEN 'RUTA-001' THEN '00000000-0000-4000-8000-000000000101'::uuid" in upgrade
    assert "WHEN 'RUTA-006' THEN '00000000-0000-4000-8000-000000000106'::uuid" in upgrade
    assert "ADD CONSTRAINT ruta_pkey PRIMARY KEY (id)" in upgrade
    assert "ADD CONSTRAINT uq_ruta_codigo UNIQUE (codigo)" in upgrade
    assert "SET id_ruta_uuid = r.id" in upgrade
    assert "WHERE r.codigo = bir.id_ruta" in upgrade
    assert "FOREIGN KEY (id_ruta)" in upgrade
    assert "REFERENCES inspecciones.ruta(id)" in upgrade
    assert "RENAME COLUMN codigo TO id" in downgrade
    assert "SET codigo_ruta = r.codigo" in downgrade


def test_inspection_route_migration_uses_route_uuid_foreign_key() -> None:
    migration = Path(
        "migrations/versions/20260831_0021_link_inspection_to_route.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260831_0020"' in migration
    assert "'SIN_RUTA', 'Sin ruta asignada'" in upgrade
    assert "ADD COLUMN ruta_id_uuid UUID" in upgrade
    assert "r.codigo = i.ruta_id" in upgrade
    assert "r.id::text = i.ruta_id" in upgrade
    assert "RENAME COLUMN ruta_id_uuid TO ruta_id" in upgrade
    assert "ADD CONSTRAINT fk_inspeccion_ruta" in upgrade
    assert "REFERENCES inspecciones.ruta(id)" in upgrade
    assert "SET codigo_ruta = r.codigo" in downgrade
    assert "RENAME COLUMN codigo_ruta TO ruta_id" in downgrade


def test_expiration_migration_clears_unfinished_inspections() -> None:
    migration = Path(
        "migrations/versions/20260903_0024_expiration_on_completion.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260901_0023"' in migration
    assert "SET fecha_vencimiento = NULL" in upgrade
    assert "WHERE fecha_realizada IS NULL" in upgrade
    assert "i.fecha_programada + p.dias_vigencia" in downgrade


def test_servicio_table_migration_moves_service_request_groups_out_of_levantamiento_opcion() -> (
    None
):
    migration = Path(
        "migrations/versions/20260917_0042_create_servicio_table.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260915_0041"' in migration
    assert "CREATE TABLE inspecciones.servicio" in upgrade
    assert "tipo_servicio         VARCHAR(50) NOT NULL" in upgrade
    assert "CONSTRAINT uq_servicio_tipo_codigo UNIQUE (tipo_servicio, codigo)" in upgrade
    assert (
        "WHERE tipo_catalogo IN {_TIPOS_SERVICIO}" in upgrade
        or "tipo_catalogo IN {_TIPOS_SERVICIO}" in upgrade
    )
    assert "DELETE FROM inspecciones.levantamiento_opcion" in upgrade
    assert "_TIPOS_SERVICIO = (" in migration
    for tipo in ("LIMPIEZA", "CERRAJERIA_MATERIAL", "REPARACION", "INSPECCION_TECNICA"):
        assert f'"{tipo}"' in migration
    assert "INSERT INTO inspecciones.levantamiento_opcion" in downgrade
    assert "DROP TABLE IF EXISTS inspecciones.servicio" in downgrade
