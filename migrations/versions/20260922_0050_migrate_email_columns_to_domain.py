"""Migrate email_inspector, email_destinatario and email_lector to the email domain.

Ninguna de las tres columnas tenía validación de formato en la base de datos. Antes
de cada ALTER COLUMN TYPE se verifica que no existan valores que no matcheen el
regex del dominio (vacíos, con espacios, placeholders históricos), para fallar con
un mensaje claro en vez del error genérico de violación de CHECK.

Revision ID: 20260922_0050
Revises: 20260922_0049
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0050"
down_revision: str | None = "20260922_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _check_sql(tabla: str, columna: str, *, nullable: bool) -> str:
    condicion = f"{columna} !~ '{_REGEX}'"
    filtro = f"{columna} IS NOT NULL AND {condicion}" if nullable else condicion
    return f"""
        DO $$
        DECLARE
            invalidos INT;
        BEGIN
            SELECT COUNT(*) INTO invalidos
            FROM inspecciones.{tabla}
            WHERE {filtro};
            IF invalidos > 0 THEN
                RAISE EXCEPTION
                    '{tabla}.{columna} tiene % fila(s) que no matchean el formato de email',
                    invalidos;
            END IF;
        END $$
    """


def upgrade() -> None:
    op.execute(_check_sql("inspeccion", "email_inspector", nullable=False))
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN email_inspector TYPE inspecciones.email
    """)

    op.execute(_check_sql("notificacion", "email_destinatario", nullable=True))
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN email_destinatario TYPE inspecciones.email
    """)

    op.execute(_check_sql("notificacion_lectura", "email_lector", nullable=False))
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ALTER COLUMN email_lector TYPE inspecciones.email
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE inspecciones.inspeccion
            ALTER COLUMN email_inspector TYPE VARCHAR(150)
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion
            ALTER COLUMN email_destinatario TYPE VARCHAR(255)
    """)
    op.execute("""
        ALTER TABLE inspecciones.notificacion_lectura
            ALTER COLUMN email_lector TYPE VARCHAR(255)
    """)
