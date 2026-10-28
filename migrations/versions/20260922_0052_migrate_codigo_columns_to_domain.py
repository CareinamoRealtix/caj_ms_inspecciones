"""Migrate ruta.codigo, servicio.codigo y levantamiento_opcion.codigo al dominio
codigo_catalogo.

ruta.codigo ya tenía la regla "no vacío" dentro de chk_ruta_valores_no_vacios (que
también cubre nombre); se reemplaza por un CHECK que solo cubre nombre, porque el
dominio pasa a cubrir codigo. servicio.codigo y levantamiento_opcion.codigo no
tenían ningún CHECK, así que se verifica primero que no existan filas vacías o con
solo espacios.

Revision ID: 20260922_0052
Revises: 20260922_0051
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0052"
down_revision: str | None = "20260922_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check_no_vacio_sql(tabla: str) -> str:
    return f"""
        DO $$
        DECLARE
            invalidos INT;
        BEGIN
            SELECT COUNT(*) INTO invalidos
            FROM inspecciones.{tabla}
            WHERE BTRIM(codigo) = '';
            IF invalidos > 0 THEN
                RAISE EXCEPTION
                    '{tabla}.codigo tiene % fila(s) vacías o con solo espacios', invalidos;
            END IF;
        END $$
    """


def upgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.ruta
            DROP CONSTRAINT chk_ruta_valores_no_vacios
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            ADD CONSTRAINT chk_ruta_nombre_no_vacio CHECK (BTRIM(nombre) <> '')
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            ALTER COLUMN codigo TYPE inspecciones.codigo_catalogo
    """)

    op.execute(_check_no_vacio_sql("servicio"))
    op.execute("""
        ALTER TABLE inspecciones.servicio
            ALTER COLUMN codigo TYPE inspecciones.codigo_catalogo
    """)

    op.execute(_check_no_vacio_sql("levantamiento_opcion"))
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_opcion
            ALTER COLUMN codigo TYPE inspecciones.codigo_catalogo
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.ruta
            ALTER COLUMN codigo TYPE VARCHAR(100)
    """)
    op.execute("""
        ALTER TABLE inspecciones.servicio
            ALTER COLUMN codigo TYPE VARCHAR(50)
    """)
    op.execute("""
        ALTER TABLE inspecciones.levantamiento_opcion
            ALTER COLUMN codigo TYPE VARCHAR(50)
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            DROP CONSTRAINT chk_ruta_nombre_no_vacio
    """)
    op.execute("""
        ALTER TABLE inspecciones.ruta
            ADD CONSTRAINT chk_ruta_valores_no_vacios
                CHECK (BTRIM(codigo) <> '' AND BTRIM(nombre) <> '')
    """)
