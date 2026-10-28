"""Drop id_inspector: email_inspector is now the only stored inspector identity.

The inspection form no longer sends the Microsoft Entra ID GUID of the
inspector, only their email; the inspector filter on /gestion and
/control now matches by email_inspector instead of id_inspector. This
column (added in 20260830_0015, nullable, no FK) is dropped along with
its index.

Revision ID: 20260907_0032
Revises: 20260907_0031
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260907_0032"
down_revision: str | None = "20260907_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_inspeccion_inspector")
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN IF EXISTS id_inspector
    """)


def downgrade() -> None:
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
