"""Remove the length limit from local property-number columns.

Revision ID: 20260901_0023
Revises: 20260901_0022
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0023"
down_revision: str | None = "20260901_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN numero_finca TYPE TEXT
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ALTER COLUMN numero_finca TYPE TEXT
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN numero_finca TYPE VARCHAR(15)
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ALTER COLUMN numero_finca TYPE VARCHAR(15)
    """)
