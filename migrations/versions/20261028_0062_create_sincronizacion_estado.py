"""Crear las tablas de estado de la sincronización (reemplazan a DynamoDB).

`sincronizacion_job` guarda el estado de la descarga y `subida_levantamiento` el de la subida por
ZIP, incluida la lista de resultados por inspección. Son registros temporales: `expira_en` marca
cuándo dejan de ser visibles y la API los borra al crear uno nuevo.

Revision ID: 20261028_0062
Revises: 20261027_0061
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261028_0062"
down_revision: str | None = "20261027_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspecciones.sincronizacion_job (
            job_id              UUID PRIMARY KEY,
            email_inspector     VARCHAR(200) NOT NULL,
            estado              VARCHAR(20) NOT NULL
                                CHECK (estado IN ('pendiente', 'procesando', 'listo', 'error')),
            s3_key              VARCHAR(500),
            error               TEXT,
            batch_job_id        VARCHAR(100),
            fecha_creacion      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_modificacion  TIMESTAMPTZ,
            expira_en           TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX idx_sincronizacion_job_expira
            ON inspecciones.sincronizacion_job(expira_en)
    """)
    op.execute("""
        COMMENT ON TABLE inspecciones.sincronizacion_job IS
            'Estado temporal de cada descarga de sincronización (job de Batch); expira_en la vence'
    """)

    op.execute("""
        CREATE TABLE inspecciones.subida_levantamiento (
            subida_id                UUID PRIMARY KEY,
            email_inspector          VARCHAR(200) NOT NULL,
            estado                   VARCHAR(20) NOT NULL
                                     CHECK (estado IN ('pendiente_carga', 'pendiente', 'procesando',
                                                       'listo', 'parcial', 'error')),
            s3_key                   VARCHAR(500) NOT NULL,
            tamano_bytes             BIGINT NOT NULL,
            sha256                   CHAR(64) NOT NULL,
            cantidad_levantamientos  INTEGER NOT NULL,
            resultados               JSONB NOT NULL DEFAULT '[]'::jsonb,
            error                    TEXT,
            batch_job_id             VARCHAR(100),
            fecha_creacion           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_modificacion       TIMESTAMPTZ,
            expira_en                TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX idx_subida_levantamiento_expira
            ON inspecciones.subida_levantamiento(expira_en)
    """)
    op.execute("""
        COMMENT ON TABLE inspecciones.subida_levantamiento IS
            'Estado temporal de cada subida de levantamientos por ZIP; expira_en la vence'
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspecciones.subida_levantamiento")
    op.execute("DROP TABLE IF EXISTS inspecciones.sincronizacion_job")
