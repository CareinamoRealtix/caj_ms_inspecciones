"""Use UUID route identifiers and preserve the current identifiers as codes.

Revision ID: 20260831_0020
Revises: 20260831_0019
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0020"
down_revision: str | None = "20260831_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            DROP CONSTRAINT IF EXISTS bien_inventario_ruta_id_ruta_fkey
    """)
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_bien_inventario_ruta_ruta")
    op.execute("""
        ALTER TABLE inspecciones.ruta
            DROP CONSTRAINT ruta_pkey
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            RENAME COLUMN id TO codigo
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            ADD COLUMN id UUID NOT NULL DEFAULT gen_random_uuid()
    """)
    op.execute("""
        UPDATE inspecciones.ruta
        SET id = CASE codigo
            WHEN 'RUTA-001' THEN '00000000-0000-4000-8000-000000000101'::uuid
            WHEN 'RUTA-002' THEN '00000000-0000-4000-8000-000000000102'::uuid
            WHEN 'RUTA-003' THEN '00000000-0000-4000-8000-000000000103'::uuid
            WHEN 'RUTA-004' THEN '00000000-0000-4000-8000-000000000104'::uuid
            WHEN 'RUTA-005' THEN '00000000-0000-4000-8000-000000000105'::uuid
            WHEN 'RUTA-006' THEN '00000000-0000-4000-8000-000000000106'::uuid
            ELSE id
        END
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            ADD CONSTRAINT ruta_pkey PRIMARY KEY (id),
            ADD CONSTRAINT uq_ruta_codigo UNIQUE (codigo)
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ADD COLUMN id_ruta_uuid UUID
    """)
    op.execute("""
        UPDATE inspecciones.bien_inventario_ruta bir
        SET id_ruta_uuid = r.id
        FROM inspecciones.ruta r
        WHERE r.codigo = bir.id_ruta
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inspecciones.bien_inventario_ruta
                WHERE id_ruta_uuid IS NULL
            ) THEN
                RAISE EXCEPTION
                    'No se pudo convertir todas las asignaciones al UUID de ruta';
            END IF;
        END
        $$
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            DROP COLUMN id_ruta
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            RENAME COLUMN id_ruta_uuid TO id_ruta
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ALTER COLUMN id_ruta SET NOT NULL,
            ADD CONSTRAINT bien_inventario_ruta_id_ruta_fkey
                FOREIGN KEY (id_ruta)
                REFERENCES inspecciones.ruta(id)
                ON DELETE RESTRICT
    """)
    op.execute("""
        CREATE INDEX idx_bien_inventario_ruta_ruta
            ON inspecciones.bien_inventario_ruta(id_ruta)
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.ruta.id IS
            'Identificador UUID interno de la ruta'
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.ruta.codigo IS
            'Código funcional único de la ruta, por ejemplo RUTA-001'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            DROP CONSTRAINT IF EXISTS bien_inventario_ruta_id_ruta_fkey
    """)
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_bien_inventario_ruta_ruta")
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ADD COLUMN codigo_ruta VARCHAR(100)
    """)
    op.execute("""
        UPDATE inspecciones.bien_inventario_ruta bir
        SET codigo_ruta = r.codigo
        FROM inspecciones.ruta r
        WHERE r.id = bir.id_ruta
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            DROP COLUMN id_ruta
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            RENAME COLUMN codigo_ruta TO id_ruta
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ALTER COLUMN id_ruta SET NOT NULL
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            DROP CONSTRAINT ruta_pkey,
            DROP CONSTRAINT uq_ruta_codigo,
            DROP COLUMN id
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            RENAME COLUMN codigo TO id
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            ADD CONSTRAINT ruta_pkey PRIMARY KEY (id)
    """)
    op.execute("""
        ALTER TABLE inspecciones.bien_inventario_ruta
            ADD CONSTRAINT bien_inventario_ruta_id_ruta_fkey
                FOREIGN KEY (id_ruta)
                REFERENCES inspecciones.ruta(id)
                ON DELETE RESTRICT
    """)
    op.execute("""
        CREATE INDEX idx_bien_inventario_ruta_ruta
            ON inspecciones.bien_inventario_ruta(id_ruta)
    """)
