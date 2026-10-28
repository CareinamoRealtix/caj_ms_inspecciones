"""Create levantamiento_operacion, the idempotency ledger for finalization.

Each finalize request carries a client-generated id_operacion so retries
(e.g. from a mobile device that lost connectivity before receiving the
response) can be detected and replayed safely instead of duplicating or
rejecting the same submission.

Revision ID: 20260908_0035
Revises: 20260908_0034
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0035"
down_revision: str | None = "20260908_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspecciones.levantamiento_operacion (
            id_operacion        UUID PRIMARY KEY,
            id_inspeccion       UUID NOT NULL
                REFERENCES inspecciones.inspeccion(id_inspeccion) ON DELETE CASCADE,
            contenido_hash      CHAR(64) NOT NULL,
            id_levantamiento    UUID NOT NULL
                REFERENCES inspecciones.levantamiento_inspeccion(id_levantamiento)
                ON DELETE CASCADE,
            respuesta           JSONB NOT NULL,
            creado_por          VARCHAR(150),
            fecha_creacion      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX idx_levantamiento_operacion_inspeccion
            ON inspecciones.levantamiento_operacion(id_inspeccion)
    """)

    op.execute("""
        COMMENT ON TABLE inspecciones.levantamiento_operacion IS
            'Registro de idempotencia para finalizar levantamientos: permite reintentos seguros'
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspecciones.levantamiento_operacion")
