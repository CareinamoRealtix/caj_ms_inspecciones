import uuid
from pathlib import Path
from typing import Any

from app.infrastructure.database.notificacion_repository import NotificacionRepository


class RecordingPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.calls.append(("fetch", sql, args))
        return []

    async def fetchval(self, sql: str, *args: Any) -> int:
        self.calls.append(("fetchval", sql, args))
        return 0

    async def fetchrow(self, sql: str, *args: Any) -> None:
        self.calls.append(("fetchrow", sql, args))
        return None

    async def execute(self, sql: str, *args: Any) -> None:
        self.calls.append(("execute", sql, args))


def _compact(sql: str) -> str:
    return " ".join(sql.split())


async def test_list_for_user_defaults_to_active_states_and_matches_email_or_roles() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]

    await repo.list_for_user("inspector@example.com", ["INSPECTOR"], None, pagina=1, tamanio=15)

    fetch_call, fetchval_call = pool.calls
    fetch_sql = _compact(fetch_call[1])
    assert "AND (n.email_destinatario = $1 OR n.rol_destino = ANY($2::varchar[]))" in fetch_sql
    assert "n.creado_por AS creador" in fetch_sql
    assert "COALESCE(l.fue_vista, FALSE) AS fue_vista" in fetch_sql
    assert (
        "THEN 'SILENCIADA' ELSE 'NO_LEIDA' END) = ANY($3::varchar[])" in fetch_sql
    )
    assert "ORDER BY n.fecha_creacion DESC" in fetch_sql
    assert fetch_call[2] == (
        "inspector@example.com",
        ["INSPECTOR"],
        ["NO_LEIDA"],
        15,
        0,
    )
    assert fetchval_call[2] == ("inspector@example.com", ["INSPECTOR"], ["NO_LEIDA"])


async def test_list_for_user_honors_explicit_estado_filter() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]

    await repo.list_for_user(
        "inspector@example.com", [], ["SILENCIADA"], pagina=2, tamanio=10
    )

    fetch_call, _ = pool.calls
    assert fetch_call[2] == ("inspector@example.com", [], ["SILENCIADA"], 10, 10)


async def test_count_no_leidas_matches_email_or_roles_and_missing_lectura() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]

    await repo.count_no_leidas("inspector@example.com", ["INSPECTOR", "OFICIAL_BIENES_ADQUIRIDOS"])

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "AND (n.email_destinatario = $1 OR n.rol_destino = ANY($2::varchar[]))" in compact_sql
    assert "AND l.id_notificacion IS NULL" in compact_sql
    assert args == ("inspector@example.com", ["INSPECTOR", "OFICIAL_BIENES_ADQUIRIDOS"])


async def test_marcar_vista_upserts_fue_vista_and_fecha_vista_independent_of_silenciado() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]
    id_notificacion = uuid.uuid4()

    await repo.marcar_vista(id_notificacion, "a@example.com")

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "INSERT INTO inspecciones.notificacion_lectura" in compact_sql
    assert "fue_vista, fecha_vista" in compact_sql
    assert "ON CONFLICT (id_notificacion, email_lector)" in compact_sql
    assert "DO UPDATE SET fue_vista = TRUE, fecha_vista = NOW()" in compact_sql
    assert "estado_lector" not in compact_sql
    assert args == (id_notificacion, "a@example.com")


async def test_marcar_silenciada_upserts_fue_silenciada_and_fecha_silenciada() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]
    id_notificacion = uuid.uuid4()

    await repo.marcar_silenciada(id_notificacion, "a@example.com")

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "INSERT INTO inspecciones.notificacion_lectura" in compact_sql
    assert "fue_silenciada, fecha_silenciada" in compact_sql
    assert "ON CONFLICT (id_notificacion, email_lector)" in compact_sql
    assert "DO UPDATE SET fue_silenciada = TRUE, fecha_silenciada = NOW()" in compact_sql
    assert "fue_vista" not in compact_sql
    assert args == (id_notificacion, "a@example.com")


async def test_marcar_vista_y_silenciada_sets_both_flags() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]
    id_notificacion = uuid.uuid4()

    await repo.marcar_vista_y_silenciada(id_notificacion, "a@example.com")

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "INSERT INTO inspecciones.notificacion_lectura" in compact_sql
    assert "fue_vista, fecha_vista, fue_silenciada, fecha_silenciada" in compact_sql
    assert (
        "DO UPDATE SET fue_vista = TRUE, fecha_vista = NOW(),"
        " fue_silenciada = TRUE, fecha_silenciada = NOW()" in compact_sql
    )
    assert args == (id_notificacion, "a@example.com")


async def test_get_ultima_activa_por_referencia_matches_email_referencia_and_tipo() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]
    referencia_id = uuid.uuid4()

    await repo.get_ultima_activa_por_referencia(
        "inspector@example.com", "inspeccion", referencia_id, "INSPECCION_PROXIMA_A_VENCER"
    )

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "SELECT n.id_notificacion" in compact_sql
    assert "AND n.estado_notificacion = 'ACTIVA'" in compact_sql
    assert "ORDER BY n.fecha_creacion DESC" in compact_sql
    assert "LIMIT 1" in compact_sql
    assert args == (
        "inspector@example.com",
        "inspeccion",
        referencia_id,
        "INSPECCION_PROXIMA_A_VENCER",
    )


async def test_close_previous_scopes_by_rol_or_email_reference_and_type() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]
    referencia_id = uuid.uuid4()

    await repo.close_previous(
        "INSPECTOR", None, "INSPECCION", referencia_id, "PROXIMA_A_VENCER"
    )

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "SET estado_notificacion = 'CERRADA', fecha_cerrada = NOW()" in compact_sql
    assert "WHERE (rol_destino = $1 OR email_destinatario = $2)" in compact_sql
    assert "AND estado_notificacion = 'ACTIVA'" in compact_sql
    assert args == ("INSPECTOR", None, "INSPECCION", referencia_id, "PROXIMA_A_VENCER")


async def test_insert_creates_a_single_row() -> None:
    pool = RecordingPool()
    repo = NotificacionRepository(pool)  # type: ignore[arg-type]
    referencia_id = uuid.uuid4()

    await repo.insert(
        {
            "rol_destino": "INSPECTOR",
            "email_destinatario": None,
            "tipo_notificacion": "PROXIMA_A_VENCER",
            "titulo": "Alerta",
            "mensaje": "La inspección No. 1 se encuentra próxima a vencer",
            "referencia_tipo": "INSPECCION",
            "referencia_id": referencia_id,
            "creado_por": "sistema@example.com",
        }
    )

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert compact_sql.count("INSERT INTO inspecciones.notificacion") == 1
    assert "RETURNING id_notificacion" in compact_sql
    assert args == (
        "INSPECTOR",
        None,
        "PROXIMA_A_VENCER",
        "Alerta",
        "La inspección No. 1 se encuentra próxima a vencer",
        "INSPECCION",
        referencia_id,
        "sistema@example.com",
    )


def test_notificacion_migration_restructures_for_roles_and_per_user_reads() -> None:
    migration = Path(
        "migrations/versions/20260909_0036_restructure_notificacion_por_rol.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260908_0035"' in migration
    assert "ADD COLUMN rol_destino VARCHAR(50)" in upgrade
    assert "ADD COLUMN estado_notificacion VARCHAR(20)" in upgrade
    assert "ALTER COLUMN email_destinatario DROP NOT NULL" in upgrade
    assert "ADD CONSTRAINT chk_notificacion_destinatario_unico" in upgrade
    assert "CREATE TABLE inspecciones.notificacion_lectura" in upgrade
    assert "PRIMARY KEY (id_notificacion, email_lector)" in upgrade
    assert "CHECK (estado_lector IN ('VISTA', 'SILENCIADA'))" in upgrade
    assert "INSERT INTO inspecciones.notificacion_lectura" in upgrade
    assert "DROP COLUMN rol_origen" in upgrade
    assert "idx_notificacion_rol_destino" in upgrade
    assert "idx_notificacion_email_destinatario" in upgrade
    assert "DROP TABLE IF EXISTS inspecciones.notificacion_lectura" in downgrade


def test_fue_vista_migration_decouples_seen_from_silenciado() -> None:
    migration = Path(
        "migrations/versions/20260912_0037_add_fue_vista_to_notificacion_lectura.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260909_0036"' in migration
    assert "ADD COLUMN fue_vista BOOLEAN NOT NULL DEFAULT FALSE" in upgrade
    assert "SET fue_vista = TRUE" in upgrade
    assert "WHERE estado_lector = 'VISTA'" in upgrade
    assert "SET estado_lector = NULL" in upgrade
    assert "DROP CONSTRAINT notificacion_lectura_estado_lector_check" in upgrade
    assert "ALTER COLUMN estado_lector DROP NOT NULL" in upgrade
    assert (
        "CHECK (estado_lector IS NULL OR estado_lector = 'SILENCIADA')" in upgrade
    )
    assert "DROP COLUMN fue_vista" in downgrade


def test_fue_silenciada_migration_replaces_estado_lector_with_a_boolean() -> None:
    migration = Path(
        "migrations/versions/20260912_0038_add_fue_silenciada_to_notificacion_lectura.py"
    ).read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade", maxsplit=1)

    assert 'down_revision: str | None = "20260912_0037"' in migration
    assert "ADD COLUMN fue_silenciada BOOLEAN NOT NULL DEFAULT FALSE" in upgrade
    assert "SET fue_silenciada = TRUE" in upgrade
    assert "WHERE estado_lector = 'SILENCIADA'" in upgrade
    assert "DROP CONSTRAINT chk_notificacion_lectura_estado_lector" in upgrade
    assert "DROP COLUMN estado_lector" in upgrade
    assert "ADD COLUMN estado_lector VARCHAR(20)" in downgrade
    assert "DROP COLUMN fue_silenciada" in downgrade
