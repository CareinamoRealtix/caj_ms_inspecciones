"""Seed inventory route assignments from the provided inventory export.

Revision ID: 20260831_0019
Revises: 20260831_0018
Create Date: 2026-08-31
"""

import csv
import uuid
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0019"
down_revision: str | None = "20260831_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CSV_PATH = Path(__file__).parents[2] / "data-1788200648750.csv"
_ROUTE_IDS = (
    "RUTA-001",
    "RUTA-002",
    "RUTA-003",
    "RUTA-004",
    "RUTA-005",
    "RUTA-006",
)


def _representative_property_number(raw_values: str) -> str | None:
    if raw_values == "{}":
        return None
    return raw_values.removeprefix("{").removesuffix("}").split(",", maxsplit=1)[0]


def _load_assignments() -> list[dict[str, str | None]]:
    if not _CSV_PATH.exists():
        return []

    with _CSV_PATH.open(newline="", encoding="ascii") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames != ["id_bien_inventario", "numeros_finca"]:
            raise ValueError("El CSV de asignaciones no tiene las columnas esperadas")

        assignments = [
            {
                "id_bien_inventario": row["id_bien_inventario"],
                "id_ruta": _ROUTE_IDS[index % len(_ROUTE_IDS)],
                "numero_finca": _representative_property_number(row["numeros_finca"]),
            }
            for index, row in enumerate(reader)
        ]

    ids = [row["id_bien_inventario"] for row in assignments]
    if not assignments:
        raise ValueError("El CSV de asignaciones está vacío")
    if len(ids) != len(set(ids)):
        raise ValueError("El CSV contiene id_bien_inventario duplicados")
    for row in assignments:
        uuid.UUID(row["id_bien_inventario"] or "")
        numero_finca = row["numero_finca"]
        if numero_finca is not None and len(numero_finca) > 15:
            raise ValueError("El CSV contiene un numero_finca mayor de 15 caracteres")
    return assignments


def upgrade() -> None:
    # numero_finca must stay nullable going forward regardless of whether the historical
    # export below is available: production code upserts bienes without an assigned finca.
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ALTER COLUMN numero_finca DROP NOT NULL
    """)

    assignments = _load_assignments()
    if not assignments:
        return

    op.execute("""
        CREATE TEMPORARY TABLE seed_bien_inventario_ruta (
            id_bien_inventario UUID PRIMARY KEY,
            id_ruta            VARCHAR(100) NOT NULL,
            numero_finca       VARCHAR(15)
        ) ON COMMIT DROP
    """)
    seed_table = sa.table(
        "seed_bien_inventario_ruta",
        sa.column("id_bien_inventario", sa.Uuid()),
        sa.column("id_ruta", sa.String(length=100)),
        sa.column("numero_finca", sa.String(length=15)),
    )
    op.bulk_insert(seed_table, assignments)
    op.execute("""
        INSERT INTO inspecciones.bien_inventario_ruta (
            id_bien_inventario,
            id_ruta,
            numero_finca
        )
        SELECT id_bien_inventario, id_ruta, numero_finca
        FROM seed_bien_inventario_ruta
        ON CONFLICT (id_bien_inventario) DO UPDATE SET
            id_ruta = EXCLUDED.id_ruta,
            numero_finca = EXCLUDED.numero_finca
    """)


def downgrade() -> None:
    assignments = _load_assignments()
    if assignments:
        assignment_ids = sa.table(
            "bien_inventario_ruta",
            sa.column("id_bien_inventario", sa.Uuid()),
            schema="inspecciones",
        )
        op.execute(
            assignment_ids.delete().where(
                assignment_ids.c.id_bien_inventario.in_(
                    [row["id_bien_inventario"] for row in assignments]
                )
            )
        )
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ALTER COLUMN numero_finca SET NOT NULL
    """)
