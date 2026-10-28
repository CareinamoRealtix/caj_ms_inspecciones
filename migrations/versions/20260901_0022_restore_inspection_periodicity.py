"""Restore the persisted periodicity relationship on inspections.

Revision ID: 20260901_0022
Revises: 20260831_0021
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0022"
down_revision: str | None = "20260831_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN id_periodicidad INTEGER,
            ADD CONSTRAINT fk_inspeccion_periodicidad
                FOREIGN KEY (id_periodicidad)
                REFERENCES inspecciones.periodicidad(id_periodicidad)
                ON DELETE RESTRICT
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion i
        SET id_periodicidad = p.id_periodicidad
        FROM inspecciones.periodicidad p
        WHERE i.fecha_vencimiento IS NOT NULL
          AND i.fecha_programada IS NOT NULL
          AND i.fecha_vencimiento - i.fecha_programada = p.dias_vigencia
    """)
    op.execute("""
        CREATE INDEX idx_inspeccion_periodicidad
            ON inspecciones.inspeccion(id_periodicidad)
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.id_periodicidad IS
            'Periodicidad seleccionada para calcular la fecha de vencimiento'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_inspeccion_periodicidad")
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS fk_inspeccion_periodicidad,
            DROP COLUMN IF EXISTS id_periodicidad
    """)
