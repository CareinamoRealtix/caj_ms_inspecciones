"""Recodify chk_ocupante_datos to the new ESTADO_OCUPACION catalog code.

estado_ocupacion now stores a levantamiento_opcion code (DESOCUPADO/OCUPADO/
INVADIDO) instead of the old free-text 'Desocupado', so the CHECK constraint
that exempts unoccupied properties from requiring occupant data must compare
against the new literal.

Revision ID: 20260908_0034
Revises: 20260908_0033
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0034"
down_revision: str | None = "20260908_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_inspeccion
            DROP CONSTRAINT chk_ocupante_datos
    """)
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_inspeccion
            ADD CONSTRAINT chk_ocupante_datos CHECK (
                estado_ocupacion = 'DESOCUPADO'
                OR (nombre_ocupante IS NOT NULL AND numero_contacto_ocupante IS NOT NULL)
            )
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_inspeccion
            DROP CONSTRAINT chk_ocupante_datos
    """)
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_inspeccion
            ADD CONSTRAINT chk_ocupante_datos CHECK (
                estado_ocupacion = 'Desocupado'
                OR (nombre_ocupante IS NOT NULL AND numero_contacto_ocupante IS NOT NULL)
            )
    """)
