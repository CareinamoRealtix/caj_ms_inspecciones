"""Document expiration calculation at inspection completion.

Revision ID: 20260903_0024
Revises: 20260901_0023
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260903_0024"
down_revision: str | None = "20260901_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE inspecciones.inspeccion
        SET fecha_vencimiento = NULL
        WHERE fecha_realizada IS NULL
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.fecha_vencimiento IS
            'Fecha realizada más días de periodicidad; NULL hasta finalizar'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE inspecciones.inspeccion AS i
        SET fecha_vencimiento = i.fecha_programada + p.dias_vigencia
        FROM inspecciones.periodicidad AS p
        WHERE p.id_periodicidad = i.id_periodicidad
          AND i.fecha_realizada IS NULL
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.fecha_vencimiento IS
            'Fecha programada más los días calendario de la periodicidad seleccionada'
    """)
