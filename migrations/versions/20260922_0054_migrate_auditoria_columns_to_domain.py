"""Migrate creado_por/modificado_por to the usuario_auditoria domain.

Todas nullable, sin CHECK previo en base de datos. Se verifica antes de cada
ALTER COLUMN TYPE que no existan filas no nulas que no matcheen el formato de
email (el dominio no evalúa NULL).

Revision ID: 20260922_0054
Revises: 20260922_0053
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0054"
down_revision: str | None = "20260922_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

_COLUMNAS = (
    ("inspeccion", "creado_por"),
    ("inspeccion", "modificado_por"),
    ("levantamiento_inspeccion", "creado_por"),
    ("levantamiento_operacion", "creado_por"),
    ("notificacion", "creado_por"),
)


def _check_sql(tabla: str, columna: str) -> str:
    return f"""
        DO $$
        DECLARE
            invalidos INT;
        BEGIN
            SELECT COUNT(*) INTO invalidos
            FROM inspecciones.{tabla}
            WHERE {columna} IS NOT NULL AND {columna} !~ '{_REGEX}';
            IF invalidos > 0 THEN
                RAISE EXCEPTION
                    '{tabla}.{columna} tiene % fila(s) que no matchean el formato de email',
                    invalidos;
            END IF;
        END $$
    """


def upgrade() -> None:
    for tabla, columna in _COLUMNAS:
        op.execute(_check_sql(tabla, columna))
        op.execute(f"""
            ALTER TABLE inspecciones.{tabla}
                ALTER COLUMN {columna} TYPE inspecciones.usuario_auditoria
        """)


def downgrade() -> None:
    for tabla, columna in _COLUMNAS:
        op.execute(f"""
            ALTER TABLE inspecciones.{tabla}
                ALTER COLUMN {columna} TYPE VARCHAR(150)
        """)
