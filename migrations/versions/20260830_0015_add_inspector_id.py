"""Add the Microsoft Entra ID inspector identifier.

Revision ID: 20260830_0015
Revises: 20260829_0014
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0015"
down_revision: str | None = "20260829_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN id_inspector UUID
    """)
    op.execute("""
        CREATE INDEX idx_inspeccion_inspector
            ON inspecciones.inspeccion(id_inspector)
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.id_inspector IS
            'Identificador del inspector en Microsoft Entra ID; NULL solo para registros históricos'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.fecha_vencimiento IS
            'Fecha programada más los días calendario de la periodicidad seleccionada'
    """)


def downgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.fecha_vencimiento IS
            'TODO: cálculo pendiente de definición; temporalmente siempre NULL'
    """)
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_inspeccion_inspector")
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN IF EXISTS id_inspector
    """)
