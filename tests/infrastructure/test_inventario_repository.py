import uuid
from datetime import date
from pathlib import Path
from typing import Any

from app.infrastructure.database.inspeccion_repository import InspeccionRepository


class RecordingPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.calls.append(("fetch", sql, args))
        return []

    async def fetchval(self, sql: str, *args: Any) -> int:
        self.calls.append(("fetchval", sql, args))
        return 0


def _compact(sql: str) -> str:
    return " ".join(sql.split())


async def test_management_catalogs_read_only_the_service_view() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_catalogos_gestion()

    sql = _compact(pool.calls[0][1])
    assert "FROM inspecciones.v_catalogos_gestion" in sql
    assert "bien." not in sql


async def test_inventory_page_uses_active_filter_limit_and_offset() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(pagina=1, tamanio=15)

    data_call, count_call = pool.calls
    data_sql = _compact(data_call[1])
    count_sql = _compact(count_call[1])
    assert "FROM inspecciones.v_consulta_inventario v" in data_sql
    assert "v.es_activo = TRUE" in data_sql
    assert "v.es_activo = TRUE" in count_sql
    # Los bienes «Vendido» (id 6) no se listan, pero los que no tienen estatus sí.
    assert "v.id_estatus_bien IS DISTINCT FROM 6" in data_sql
    assert "v.id_estatus_bien IS DISTINCT FROM 6" in count_sql
    assert (
        "(v.estado_inventario IS NULL OR LOWER(v.estado_inventario) <> 'borrador')"
        in data_sql
    )
    assert (
        "(v.estado_inventario IS NULL OR LOWER(v.estado_inventario) <> 'borrador')"
        in count_sql
    )
    assert "LIMIT $1 OFFSET $2" in data_sql
    latest_expiration = (
        "( SELECT completed_i.fecha_vencimiento "
        "FROM inspecciones.inspeccion completed_i "
        "WHERE completed_i.id_bien_inventario = v.id_bien_inventario "
        "AND completed_i.fecha_realizada IS NOT NULL "
        "AND completed_i.activa = FALSE "
        "ORDER BY completed_i.fecha_realizada DESC, "
        "completed_i.numero_inspeccion DESC LIMIT 1 )"
    )
    assert (
        "EXISTS ( SELECT 1 FROM inspecciones.inspeccion i "
        "WHERE i.id_bien_inventario = v.id_bien_inventario )"
        in data_sql
    )
    assert (
        f"ORDER BY CASE WHEN {latest_expiration} IS NULL THEN 3 "
        f"WHEN {latest_expiration} < CURRENT_DATE THEN 0 "
        f"WHEN {latest_expiration} <= CURRENT_DATE + INTERVAL '10 days' THEN 1 "
        f"ELSE 2 END, {latest_expiration} ASC NULLS LAST, "
        "v.fecha_ingreso_inventario DESC NULLS LAST, v.no_registro DESC"
        in data_sql
    )
    assert data_call[2] == (15, 0)
    assert count_call[2] == ()

    expected_management_columns = [
        "v.numeros_finca",
        "v.id_provincia",
        "v.id_distrito",
        "v.distrito",
        "v.id_corregimiento",
        "v.corregimiento",
        "v.barriada_sector",
        "v.direccion",
        "v.numero_lote",
        "v.latitud",
        "v.longitud",
        "v.url_ubicacion_geoespacial",
        "v.fecha_creacion",
        "AS fecha_vencimiento_orden",
    ]
    for column in expected_management_columns:
        assert column in data_sql
    # La ruta asignada por bien+finca se resuelve aparte (ver
    # get_bien_inventario_rutas_for_bienes), no con un JOIN a nivel de bien:
    # bien_inventario_ruta puede tener varias filas por bien (una por finca).
    assert "bien_inventario_ruta" not in data_sql


async def test_control_inventory_includes_bienes_without_any_inspection() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(
        pagina=1,
        tamanio=15,
        requiere_inspeccion_finalizada=True,
    )

    data_call, count_call = pool.calls
    data_sql = _compact(data_call[1])
    count_sql = _compact(count_call[1])
    # /control también excluye los bienes «Vendido».
    assert "v.id_estatus_bien IS DISTINCT FROM 6" in data_sql
    assert "v.id_estatus_bien IS DISTINCT FROM 6" in count_sql
    # /control ya no exige que el bien tenga ninguna inspección (ni activa ni
    # finalizada): debe incluir también los que nunca han sido inspeccionados.
    assert "completed_filter_i" not in data_sql
    assert "NOT EXISTS" not in data_sql
    assert (
        "EXISTS ( SELECT 1 FROM inspecciones.inspeccion i "
        "WHERE i.id_bien_inventario = v.id_bien_inventario )"
        not in data_sql
    )
    assert "v.es_activo = TRUE" in data_sql
    assert "v.es_activo = TRUE" in count_sql


async def test_latest_completed_inspection_returns_its_dates_per_inventory_item() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_latest_completed_inspections_for_bienes([])
    assert pool.calls == []

    inventory_id = uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d")
    await repository.get_latest_completed_inspections_for_bienes([inventory_id])

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "SELECT DISTINCT ON (i.id_bien_inventario, i.numero_finca)" in compact_sql
    assert "i.numero_finca" in compact_sql
    assert "i.numero_inspeccion" in compact_sql
    assert "i.fecha_realizada" in compact_sql
    assert "i.fecha_vencimiento" in compact_sql
    assert "i.fecha_realizada IS NOT NULL" in compact_sql
    assert "i.activa = FALSE" in compact_sql
    assert (
        "ORDER BY i.id_bien_inventario, i.numero_finca, i.fecha_realizada DESC, "
        "i.numero_inspeccion DESC"
        in compact_sql
    )
    assert args == ([inventory_id],)


async def test_active_inspection_returns_expiration_without_requiring_completion() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    inventory_id = uuid.UUID("6ba7b810-a334-431e-b530-10f0c8741f3d")

    await repository.get_active_inspections_for_bienes([inventory_id])

    _, sql, args = pool.calls[0]
    compact_sql = _compact(sql)
    assert "SELECT DISTINCT ON (i.id_bien_inventario, i.numero_finca)" in compact_sql
    assert "i.numero_finca" in compact_sql
    assert "i.fecha_vencimiento" in compact_sql
    assert "i.activa = TRUE" in compact_sql
    assert "i.descripcion_tipo" in compact_sql
    assert "i.fecha_realizada IS NOT NULL" not in compact_sql
    assert (
        "ORDER BY i.id_bien_inventario, i.numero_finca, i.fecha_programada DESC, "
        "i.numero_inspeccion DESC, i.id_inspeccion DESC"
        in compact_sql
    )
    assert args == ([inventory_id],)


async def test_finca_filter_uses_inventory_and_inspection_numbers() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(pagina=1, tamanio=15, numero_finca="12345")

    data_call, count_call = pool.calls
    data_sql = _compact(data_call[1])
    count_sql = _compact(count_call[1])
    inventory_match = (
        "EXISTS ( SELECT 1 FROM UNNEST(v.numeros_finca) AS nf(numero) WHERE nf.numero ILIKE $1 )"
    )
    inspection_match = (
        "EXISTS ( SELECT 1 FROM inspecciones.inspeccion finca_i "
        "WHERE finca_i.id_bien_inventario = v.id_bien_inventario "
        "AND finca_i.numero_finca ILIKE $1 )"
    )
    for sql in (data_sql, count_sql):
        assert inventory_match in sql
        assert inspection_match in sql
    assert data_call[2] == ("%12345%", 15, 0)
    assert count_call[2] == ("%12345%",)
    assert "12345" not in data_call[1]


async def test_new_entry_filter_excludes_bienes_with_any_inspection_before_pagination() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(pagina=1, tamanio=15, nuevo_ingreso=True)

    data_call, count_call = pool.calls
    expected = (
        "NOT EXISTS ( SELECT 1 FROM inspecciones.inspeccion i "
        "WHERE i.id_bien_inventario = v.id_bien_inventario )"
    )
    assert expected in _compact(data_call[1])
    assert expected in _compact(count_call[1])
    assert "MAX(active_i.fecha_programada)" in _compact(data_call[1])
    assert data_call[2] == (15, 0)
    assert count_call[2] == ()


async def test_alert_filters_use_latest_completed_and_inactive_inspection() -> None:
    expected_comparisons = {
        "TERMINO": "> CURRENT_DATE + INTERVAL '10 days'",
        "VENCIDA": "< CURRENT_DATE",
        "PROXIMA": (
            "BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '10 days'"
        ),
    }
    latest_expiration = (
        "( SELECT completed_i.fecha_vencimiento "
        "FROM inspecciones.inspeccion completed_i "
        "WHERE completed_i.id_bien_inventario = v.id_bien_inventario "
        "AND completed_i.fecha_realizada IS NOT NULL "
        "AND completed_i.activa = FALSE "
        "ORDER BY completed_i.fecha_realizada DESC, "
        "completed_i.numero_inspeccion DESC LIMIT 1 )"
    )

    for alerta, comparison in expected_comparisons.items():
        pool = RecordingPool()
        repository = InspeccionRepository(pool)  # type: ignore[arg-type]

        await repository.get_inventario(pagina=1, tamanio=15, alerta=alerta)

        data_call, count_call = pool.calls
        for sql in (_compact(data_call[1]), _compact(count_call[1])):
            assert f"{latest_expiration} {comparison}" in sql
            assert "i.id_estado_inspeccion" not in sql
        assert data_call[2] == (15, 0)
        assert count_call[2] == ()


async def test_route_filter_uses_inventory_route_assignment() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    route_id = uuid.UUID("00000000-0000-4000-8000-000000000101")

    await repository.get_inventario(pagina=1, tamanio=15, ruta=route_id)

    data_call, count_call = pool.calls
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert "EXISTS ( SELECT 1 FROM inspecciones.bien_inventario_ruta bir" in sql
        assert "bir.id_bien_inventario = v.id_bien_inventario" in sql
        assert "bir.id_ruta = $1" in sql
    assert "completed_i.fecha_realizada IS NOT NULL" in _compact(data_call[1])
    assert "completed_i.activa = FALSE" in _compact(data_call[1])
    assert "active_i.activa = TRUE" not in _compact(count_call[1])
    assert data_call[2] == (route_id, 15, 0)
    assert count_call[2] == (route_id,)


async def test_inspector_filter_uses_latest_inspection_regardless_of_status() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    inspector_email = "inspector@example.com"

    await repository.get_inventario(
        pagina=1,
        tamanio=15,
        inspector=inspector_email,
    )

    data_call, count_call = pool.calls
    expected = (
        "( SELECT i.email_inspector FROM inspecciones.inspeccion i "
        "WHERE i.id_bien_inventario = v.id_bien_inventario "
        "ORDER BY i.numero_inspeccion DESC LIMIT 1 ) = $1"
    )
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert expected in sql
        assert (
            "WHERE i.id_bien_inventario = v.id_bien_inventario "
            "AND i.fecha_realizada"
        ) not in sql
        assert "i.id_estado_inspeccion" not in sql
        assert "i.id_inspector" not in sql
    assert data_call[2] == (inspector_email, 15, 0)
    assert count_call[2] == (inspector_email,)


async def test_last_inspection_month_filter_uses_latest_completed_inspection() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(
        pagina=1,
        tamanio=15,
        month_last_insp="2026-08",
    )

    data_call, count_call = pool.calls
    latest_realizada = (
        "( SELECT completed_i.fecha_realizada "
        "FROM inspecciones.inspeccion completed_i "
        "WHERE completed_i.id_bien_inventario = v.id_bien_inventario "
        "AND completed_i.fecha_realizada IS NOT NULL "
        "AND completed_i.activa = FALSE "
        "ORDER BY completed_i.fecha_realizada DESC, "
        "completed_i.numero_inspeccion DESC LIMIT 1 )"
    )
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert f"{latest_realizada} >= TO_DATE($1, 'YYYY-MM')" in sql
        assert f"{latest_realizada} < TO_DATE($2, 'YYYY-MM') + INTERVAL '1 month'" in sql
    assert data_call[2] == ("2026-08", "2026-08", 15, 0)
    assert count_call[2] == ("2026-08", "2026-08")


async def test_expiration_month_filter_uses_latest_completed_expiration() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(
        pagina=1,
        tamanio=15,
        month_expiration="2026-10",
    )

    data_call, count_call = pool.calls
    latest_expiration = (
        "( SELECT completed_i.fecha_vencimiento "
        "FROM inspecciones.inspeccion completed_i "
        "WHERE completed_i.id_bien_inventario = v.id_bien_inventario "
        "AND completed_i.fecha_realizada IS NOT NULL "
        "AND completed_i.activa = FALSE "
        "ORDER BY completed_i.fecha_realizada DESC, "
        "completed_i.numero_inspeccion DESC LIMIT 1 )"
    )
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert f"{latest_expiration} >= TO_DATE($1, 'YYYY-MM')" in sql
        assert (
            f"{latest_expiration} < TO_DATE($2, 'YYYY-MM') + INTERVAL '1 month'"
            in sql
        )
    assert data_call[2] == ("2026-10", "2026-10", 15, 0)
    assert count_call[2] == ("2026-10", "2026-10")


async def test_last_inspection_date_range_filters_latest_completed_inspection() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(
        pagina=1,
        tamanio=15,
        fecha_desde=date(2026, 8, 1),
        fecha_hasta=date(2026, 8, 31),
    )

    data_call, count_call = pool.calls
    latest_realizada = (
        "( SELECT completed_i.fecha_realizada "
        "FROM inspecciones.inspeccion completed_i "
        "WHERE completed_i.id_bien_inventario = v.id_bien_inventario "
        "AND completed_i.fecha_realizada IS NOT NULL "
        "AND completed_i.activa = FALSE "
        "ORDER BY completed_i.fecha_realizada DESC, "
        "completed_i.numero_inspeccion DESC LIMIT 1 )"
    )
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert f"{latest_realizada} >= $1" in sql
        assert f"{latest_realizada} <= $2" in sql
    expected_filters = (date(2026, 8, 1), date(2026, 8, 31))
    assert data_call[2] == (*expected_filters, 15, 0)
    assert count_call[2] == expected_filters


async def test_combined_filters_share_conditions_between_data_and_count() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(
        pagina=3,
        tamanio=10,
        id_estatus_bien=4,
        id_provincia=8,
        id_distrito=9,
        id_corregimiento=10,
    )

    data_call, count_call = pool.calls
    data_sql = _compact(data_call[1])
    count_sql = _compact(count_call[1])
    expected_conditions = [
        "v.es_activo = TRUE",
        "v.id_estatus_bien = $1",
        "v.id_provincia = $2",
        "v.id_distrito = $3",
        "v.id_corregimiento = $4",
    ]
    for condition in expected_conditions:
        assert condition in data_sql
        assert condition in count_sql
    assert data_call[2][:-2] == count_call[2]
    assert data_call[2][-2:] == (10, 20)


async def test_historico_returns_only_finalized_inspections() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_historico_by_finca("3099", pagina=1, tamanio=15)

    count_call, data_call = pool.calls
    assert "i.id_inspeccion" in _compact(data_call[1])
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert "i.numero_finca ILIKE $1 ESCAPE '\\'" in sql
        assert "i.activa = FALSE" in sql
        assert "i.fecha_realizada IS NOT NULL" in sql
    assert data_call[2] == ("%3099%", 15, 0)
    assert count_call[2] == ("%3099%",)


async def test_historico_without_numero_finca_filters_by_inspector_only() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_historico_by_finca(
        None, pagina=1, tamanio=15, inspector="Inspector@Example.com"
    )

    count_call, data_call = pool.calls
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert "numero_finca ILIKE" not in sql
        assert "LOWER(i.email_inspector) = LOWER($1)" in sql
        assert "i.activa = FALSE" in sql
        assert "i.fecha_realizada IS NOT NULL" in sql
    assert data_call[2] == ("Inspector@Example.com", 15, 0)
    assert count_call[2] == ("Inspector@Example.com",)


async def test_historico_without_any_filter_returns_empty_without_querying() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    rows, total = await repository.get_historico_by_finca(None, pagina=1, tamanio=15)

    assert (rows, total) == ([], 0)
    assert pool.calls == []


async def test_historico_applies_realized_date_range_filter() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_historico_by_finca(
        "3099",
        pagina=1,
        tamanio=15,
        fecha_desde=date(2026, 8, 1),
        fecha_hasta=date(2026, 8, 31),
    )

    count_call, data_call = pool.calls
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert "i.fecha_realizada >= $2" in sql
        assert "i.fecha_realizada <= $3" in sql
    assert data_call[2][:3] == ("%3099%", date(2026, 8, 1), date(2026, 8, 31))
    assert count_call[2] == ("%3099%", date(2026, 8, 1), date(2026, 8, 31))


async def test_historico_route_filter_uses_inventory_route_assignment() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]
    route_id = uuid.UUID("00000000-0000-4000-8000-000000000101")

    await repository.get_historico_by_finca(
        "3099", pagina=1, tamanio=15, ruta=route_id
    )

    count_call, data_call = pool.calls
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert "EXISTS ( SELECT 1 FROM inspecciones.bien_inventario_ruta bir" in sql
        assert "bir.id_bien_inventario = v.id_bien_inventario" in sql
        assert "bir.id_ruta = $2" in sql
    assert data_call[2][:2] == ("%3099%", route_id)
    assert count_call[2] == ("%3099%", route_id)


async def test_historico_inspector_filter_matches_email_case_insensitively() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_historico_by_finca(
        "3099", pagina=1, tamanio=15, inspector="inspector@example.com"
    )

    count_call, data_call = pool.calls
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert "LOWER(i.email_inspector) = LOWER($2)" in sql
    assert data_call[2][:2] == ("%3099%", "inspector@example.com")
    assert count_call[2] == ("%3099%", "inspector@example.com")


async def test_historico_last_inspection_month_filter_uses_fecha_realizada() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_historico_by_finca(
        "3099", pagina=1, tamanio=15, month_last_insp="2026-08"
    )

    count_call, data_call = pool.calls
    for sql in (_compact(data_call[1]), _compact(count_call[1])):
        assert "i.fecha_realizada >= TO_DATE($2, 'YYYY-MM')" in sql
        assert "i.fecha_realizada < TO_DATE($3, 'YYYY-MM') + INTERVAL '1 month'" in sql
    assert data_call[2][:3] == ("%3099%", "2026-08", "2026-08")
    assert count_call[2] == ("%3099%", "2026-08", "2026-08")


def test_view_aggregates_fincas_without_general_distinct() -> None:
    migration = Path(
        "migrations/versions/20260826_0004_create_consulta_inventario_view.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert "CREATE OR REPLACE VIEW inspecciones.v_consulta_inventario" in upgrade
    assert "LEFT JOIN LATERAL" in upgrade
    assert "STRING_AGG" in upgrade
    assert "ARRAY_AGG" in upgrade
    assert "SELECT *" not in upgrade
    assert "DISTINCT" not in upgrade


def test_management_view_exposes_location_and_representative_coordinates() -> None:
    migration = Path("migrations/versions/20260827_0007_expand_gestion_location_view.py").read_text(
        encoding="utf-8"
    )
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    expected_fields = [
        "cor.id_corregimiento",
        "dist.nombre AS distrito",
        "cor.nombre AS corregimiento",
        "dir.barrio AS barriada_sector",
        "dir.direccion",
        "dir.numero_lote",
        "dir.url_ubicacion_geoespacial",
        "bi.fecha_creacion",
    ]
    for field in expected_fields:
        assert field in upgrade
    assert "ST_Y(ST_PointOnSurface(dir.geom_direccion)) AS latitud" in upgrade
    assert "ST_X(ST_PointOnSurface(dir.geom_direccion)) AS longitud" in upgrade


def test_management_catalogs_view_reads_required_bien_catalogs() -> None:
    migration = Path("migrations/versions/20260827_0008_create_gestion_catalogs_view.py").read_text(
        encoding="utf-8"
    )
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert "CREATE VIEW inspecciones.v_catalogos_gestion" in upgrade
    assert "FROM bien.estatus_ocupacion" in upgrade
    assert "FROM bien.provincia" in upgrade
    assert "FROM bien.distrito" in upgrade
    assert "FROM bien.corregimiento" in upgrade
    assert "d.id_provincia::integer AS id_padre" in upgrade
    assert "c.id_distrito::integer AS id_padre" in upgrade


def test_management_catalogs_view_uses_inventory_status_catalog() -> None:
    migration = Path("migrations/versions/20260829_0013_use_inventory_status_catalog.py").read_text(
        encoding="utf-8"
    )
    upgrade = migration.split("def downgrade", maxsplit=1)[0]

    assert "CREATE OR REPLACE VIEW inspecciones.v_catalogos_gestion" in upgrade
    assert "FROM bien.estatus_bien_inventario" in upgrade
    assert "ebi.id_estatus_bien_inventario::integer AS id" in upgrade
    assert "FROM bien.estatus_ocupacion" not in upgrade


def test_application_has_no_queries_against_bien_schema() -> None:
    offenders = []
    for path in Path("app").rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        if "from bien." in source or "join bien." in source:
            offenders.append(str(path))

    assert offenders == []


async def test_inventory_page_is_paginated_by_finca_not_by_bien() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(pagina=2, tamanio=15)

    data_call, count_call = pool.calls
    data_sql = _compact(data_call[1])
    count_sql = _compact(count_call[1])
    # Cada fila de la página es un (bien, finca): LIMIT/OFFSET y COUNT operan sobre ellas.
    for sql in (data_sql, count_sql):
        assert "CROSS JOIN LATERAL" in sql
        assert "SELECT DISTINCT fc.numero AS numero_finca_item" in sql
    assert "fi.numero_finca_item," in data_sql
    assert "v.no_registro DESC, fi.numero_finca_item LIMIT $1 OFFSET $2" in data_sql
    assert data_call[2] == (15, 15)
    assert count_call[2] == ()


async def test_finca_filter_restricts_emitted_fincas_reusing_the_same_parameter() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(pagina=1, tamanio=15, numero_finca="123-456")

    data_call, count_call = pool.calls
    data_sql = _compact(data_call[1])
    assert "AND ( v.numero_finca ILIKE $1 OR fc.numero ILIKE $1 )" in data_sql
    assert data_call[2] == ("%123-456%", 15, 0)
    assert count_call[2] == ("%123-456%",)


async def test_control_emits_every_finca_of_the_bien() -> None:
    pool = RecordingPool()
    repository = InspeccionRepository(pool)  # type: ignore[arg-type]

    await repository.get_inventario(
        pagina=1, tamanio=15, requiere_inspeccion_finalizada=True
    )

    data_sql = _compact(pool.calls[0][1])
    assert "WHERE NOT EXISTS" not in data_sql.split("CROSS JOIN LATERAL")[1].split(
        ") fi"
    )[0]
