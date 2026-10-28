"""Key bien_inventario_ruta assignments by bien+finca instead of bien alone.

A bien_inventario can appear under several numero_finca values (each with
its own inspection history), but bien_inventario_ruta only keyed rows by
id_bien_inventario. Assigning a route while creating/reprogramming an
inspection for one finca silently overwrote the route stored for any other
finca of the same bien, and /gestion used that single row as the route
fallback for every finca of the bien regardless of which one it actually
belonged to.

numero_finca is nullable here (53 existing rows have none - bienes without
a finca on record yet from the initial CSV seed), so the composite key is
a UNIQUE constraint rather than a PRIMARY KEY: Postgres treats those NULLs
as distinct from one another, which is what we want, whereas a PRIMARY KEY
would require numero_finca to be NOT NULL.

Revision ID: 20260905_0026
Revises: 20260905_0025
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0026"
down_revision: str | None = "20260905_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            DROP CONSTRAINT bien_inventario_ruta_pkey
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ADD CONSTRAINT uq_bien_inventario_ruta_bien_finca
                UNIQUE (id_bien_inventario, numero_finca)
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM inspecciones.bien_inventario_ruta bir
        WHERE bir.ctid NOT IN (
            SELECT DISTINCT ON (id_bien_inventario) ctid
            FROM inspecciones.bien_inventario_ruta
            ORDER BY id_bien_inventario, numero_finca
        )
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            DROP CONSTRAINT uq_bien_inventario_ruta_bien_finca
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ADD CONSTRAINT bien_inventario_ruta_pkey
                PRIMARY KEY (id_bien_inventario)
    """)
