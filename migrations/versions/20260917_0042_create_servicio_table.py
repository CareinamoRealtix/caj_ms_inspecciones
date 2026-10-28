"""Create inspecciones.servicio and move service-request catalogs out of
levantamiento_opcion.

LIMPIEZA, CERRAJERIA_MATERIAL, REPARACION and INSPECCION_TECNICA are not form-selection
groups like the rest of levantamiento_opcion (puertas, ventanas, etc.): they describe
servicios_requeridos, which get reported to the external ms-requerimientos (órdenes de
servicio) microservice via webhook when a levantamiento is finalized. They get their own
table, keyed by tipo_servicio instead of tipo_catalogo, so that integration can evolve
independently of the rest of the levantamiento form catalog.

Revision ID: 20260917_0042
Revises: 20260915_0041
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0042"
down_revision: str | None = "20260915_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIPOS_SERVICIO = ("LIMPIEZA", "CERRAJERIA_MATERIAL", "REPARACION", "INSPECCION_TECNICA")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspecciones.servicio (
            id_servicio           BIGSERIAL PRIMARY KEY,
            tipo_servicio         VARCHAR(50) NOT NULL,
            codigo                VARCHAR(50) NOT NULL,
            nombre                VARCHAR(150) NOT NULL,
            requiere_cantidad     BOOLEAN NOT NULL DEFAULT FALSE,
            permite_descripcion   BOOLEAN NOT NULL DEFAULT FALSE,
            orden                 INTEGER NOT NULL DEFAULT 0,
            es_activo             BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_modificacion    TIMESTAMPTZ,
            CONSTRAINT uq_servicio_tipo_codigo UNIQUE (tipo_servicio, codigo)
        )
    """)

    op.execute("""
        CREATE INDEX idx_servicio_tipo
            ON inspecciones.servicio(tipo_servicio, orden, nombre)
    """)

    op.execute("""
        COMMENT ON TABLE inspecciones.servicio IS
            'Catálogo de servicios requeridos/inspección técnica reportados a '
            'ms-requerimientos (órdenes de servicio) al finalizar un levantamiento'
    """)

    op.execute(f"""
        INSERT INTO inspecciones.servicio (
            tipo_servicio, codigo, nombre, requiere_cantidad, permite_descripcion,
            orden, es_activo, fecha_creacion, fecha_modificacion
        )
        SELECT tipo_catalogo, codigo, nombre, requiere_cantidad, permite_descripcion,
               orden, es_activo, fecha_creacion, fecha_modificacion
        FROM inspecciones.levantamiento_opcion
        WHERE tipo_catalogo IN {_TIPOS_SERVICIO}
    """)

    op.execute(f"""
        DELETE FROM inspecciones.levantamiento_opcion
        WHERE tipo_catalogo IN {_TIPOS_SERVICIO}
    """)


def downgrade() -> None:
    op.execute(f"""
        INSERT INTO inspecciones.levantamiento_opcion (
            tipo_catalogo, codigo, nombre, requiere_cantidad, permite_descripcion,
            orden, es_activo, fecha_creacion, fecha_modificacion
        )
        SELECT tipo_servicio, codigo, nombre, requiere_cantidad, permite_descripcion,
               orden, es_activo, fecha_creacion, fecha_modificacion
        FROM inspecciones.servicio
        WHERE tipo_servicio IN {_TIPOS_SERVICIO}
        ON CONFLICT (tipo_catalogo, codigo) DO NOTHING
    """)

    op.execute("DROP TABLE IF EXISTS inspecciones.servicio")
