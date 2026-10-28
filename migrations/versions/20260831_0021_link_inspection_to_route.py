"""Link inspections to routes using the new UUID primary key.

Revision ID: 20260831_0021
Revises: 20260831_0020
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0021"
down_revision: str | None = "20260831_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIN_RUTA_UUID = "00000000-0000-4000-8000-000000000100"


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO inspecciones.ruta (id, codigo, nombre)
        VALUES ('{_SIN_RUTA_UUID}'::uuid, 'SIN_RUTA', 'Sin ruta asignada')
        ON CONFLICT DO NOTHING
    """)
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_inspeccion_ruta")
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS chk_inspeccion_ruta_no_vacia,
            ADD COLUMN ruta_id_uuid UUID
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion i
        SET ruta_id_uuid = r.id
        FROM inspecciones.ruta r
        WHERE r.codigo = i.ruta_id
           OR r.id::text = i.ruta_id
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inspecciones.inspeccion
                WHERE ruta_id_uuid IS NULL
            ) THEN
                RAISE EXCEPTION
                    'No se pudo convertir todas las inspecciones al UUID de ruta';
            END IF;
        END
        $$
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN ruta_id
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            RENAME COLUMN ruta_id_uuid TO ruta_id
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN ruta_id SET NOT NULL,
            ADD CONSTRAINT fk_inspeccion_ruta
                FOREIGN KEY (ruta_id)
                REFERENCES inspecciones.ruta(id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT chk_inspeccion_ruta_no_vacia
                CHECK (BTRIM(ruta_nombre) <> '')
    """)
    op.execute("""
        CREATE INDEX idx_inspeccion_ruta
            ON inspecciones.inspeccion(ruta_id)
    """)
    op.execute("""
        COMMENT ON COLUMN inspecciones.inspeccion.ruta_id IS
            'FK UUID a inspecciones.ruta(id)'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP CONSTRAINT IF EXISTS fk_inspeccion_ruta,
            DROP CONSTRAINT IF EXISTS chk_inspeccion_ruta_no_vacia
    """)
    op.execute("DROP INDEX IF EXISTS inspecciones.idx_inspeccion_ruta")
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ADD COLUMN codigo_ruta VARCHAR(100)
    """)
    op.execute("""
        UPDATE inspecciones.inspeccion i
        SET codigo_ruta = r.codigo
        FROM inspecciones.ruta r
        WHERE r.id = i.ruta_id
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            DROP COLUMN ruta_id
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            RENAME COLUMN codigo_ruta TO ruta_id
    """)
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN ruta_id SET NOT NULL,
            ADD CONSTRAINT chk_inspeccion_ruta_no_vacia
                CHECK (BTRIM(ruta_id) <> '' AND BTRIM(ruta_nombre) <> '')
    """)
    op.execute("""
        CREATE INDEX idx_inspeccion_ruta
            ON inspecciones.inspeccion(ruta_id)
    """)
    op.execute(f"""
        DELETE FROM inspecciones.ruta r
        WHERE r.id = '{_SIN_RUTA_UUID}'::uuid
          AND NOT EXISTS (
              SELECT 1
              FROM inspecciones.bien_inventario_ruta bir
              WHERE bir.id_ruta = r.id
          )
    """)
