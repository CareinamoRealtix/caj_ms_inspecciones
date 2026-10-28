"""Add the logical inventory property number to route assignments.

Revision ID: 20260831_0017
Revises: 20260830_0016
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0017"
down_revision: str | None = "20260830_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ADD COLUMN numero_finca VARCHAR(15)
    """)
    op.execute("""
        UPDATE inspecciones.bien_inventario_ruta bir
        SET numero_finca = (
            SELECT i.numero_finca
            FROM inspecciones.inspeccion i
            WHERE i.id_bien_inventario = bir.id_bien_inventario
            ORDER BY i.numero_inspeccion DESC
            LIMIT 1
        )
        WHERE bir.numero_finca IS NULL
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inspecciones.bien_inventario_ruta
                WHERE numero_finca IS NULL
            ) THEN
                RAISE EXCEPTION
                    'No se pudo obtener numero_finca para todas las asignaciones existentes';
            END IF;
        END
        $$
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ALTER COLUMN numero_finca SET NOT NULL,
            ADD CONSTRAINT chk_bien_inventario_ruta_finca_no_vacia
                CHECK (BTRIM(numero_finca) <> '')
    """)
    op.execute("""
        CREATE INDEX idx_bien_inventario_ruta_ruta
            ON inspecciones.bien_inventario_ruta(id_ruta)
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.bien_inventario_ruta.id_bien_inventario IS
            'Referencia lógica al bien de inventario; no tiene FK entre schemas'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.bien_inventario_ruta.numero_finca IS
            'Número de finca desnormalizado asociado al bien de inventario'
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS inspecciones.idx_bien_inventario_ruta_ruta
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.bien_inventario_ruta.id_bien_inventario IS NULL
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            DROP CONSTRAINT IF EXISTS chk_bien_inventario_ruta_finca_no_vacia,
            DROP COLUMN IF EXISTS numero_finca
    """)
