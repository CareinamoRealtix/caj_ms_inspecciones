"""Agregar la opción ESTADO_OCUPACION 'Parcialmente ocupada'.

Se inserta PARCIALMENTE_OCUPADO entre OCUPADO e INVADIDO. El CHECK chk_ocupante_datos ya exige
datos del ocupante para todo estado distinto de DESOCUPADO, por lo que no requiere cambios.

Revision ID: 20261027_0061
Revises: 20261027_0060
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261027_0061"
down_revision: str | None = "20261027_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE inspecciones.levantamiento_opcion
        SET orden = 4, fecha_modificacion = NOW()
        WHERE tipo_catalogo = 'ESTADO_OCUPACION' AND codigo = 'INVADIDO'
    """)
    op.execute("""
        INSERT INTO inspecciones.levantamiento_opcion
            (tipo_catalogo, codigo, nombre, requiere_cantidad, permite_descripcion, orden)
        VALUES
            ('ESTADO_OCUPACION', 'PARCIALMENTE_OCUPADO', 'Parcialmente ocupada', FALSE, FALSE, 3)
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM inspecciones.levantamiento_opcion
        WHERE tipo_catalogo = 'ESTADO_OCUPACION' AND codigo = 'PARCIALMENTE_OCUPADO'
    """)
    op.execute("""
        UPDATE inspecciones.levantamiento_opcion
        SET orden = 3, fecha_modificacion = NOW()
        WHERE tipo_catalogo = 'ESTADO_OCUPACION' AND codigo = 'INVADIDO'
    """)
