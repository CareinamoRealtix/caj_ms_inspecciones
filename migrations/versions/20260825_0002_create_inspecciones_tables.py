"""Create inspecciones tables and catalog data.

Revision ID: 20260825_0002
Revises: 20260823_0001
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0002"
down_revision: str | None = "20260823_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones.tipo_inspeccion (
            id_tipo_inspeccion        SERIAL PRIMARY KEY,
            nombre                    VARCHAR(255) NOT NULL UNIQUE,
            descripcion               VARCHAR(255),
            permite_descripcion_libre BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        INSERT INTO inspecciones.tipo_inspeccion (nombre, descripcion, permite_descripcion_libre)
        VALUES
            ('Inspección de rutina',             'Inspección periódica de rutina',                        FALSE),
            ('Inspección de nuevo ingreso',      'Primera inspección al incorporar el bien al inventario', FALSE),
            ('Inspección por recibido conforme', 'Inspección al recibir el bien conforme',                 FALSE),
            ('Otras inspección',                 'Otro tipo de inspección no clasificado',                 TRUE)
        ON CONFLICT (nombre) DO NOTHING
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones.periodicidad (
            id_periodicidad SERIAL PRIMARY KEY,
            nombre          VARCHAR(255) NOT NULL UNIQUE,
            dias_habiles    INT NOT NULL CHECK (dias_habiles > 0)
        )
    """)

    op.execute("""
        INSERT INTO inspecciones.periodicidad (nombre, dias_habiles)
        VALUES
            ('Diaria',       1),
            ('Semanal',      5),
            ('Quincenal',   10),
            ('Mensual',     22),
            ('Bimensual',   44),
            ('Trimestral',  65),
            ('Semestral',  130),
            ('Anual',      261)
        ON CONFLICT (nombre) DO NOTHING
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones.estado_inspeccion (
            id_estado_inspeccion SERIAL PRIMARY KEY,
            nombre               VARCHAR(255) NOT NULL UNIQUE,
            descripcion          VARCHAR(255),
            color_badge          VARCHAR(20)
        )
    """)

    op.execute("""
        INSERT INTO inspecciones.estado_inspeccion (nombre, descripcion, color_badge)
        VALUES
            ('Activa',       'Inspección asignada al inspector',                   '#28a745'),
            ('En proceso',   'Adelantada por el inspector sin finalización',       '#ffc107'),
            ('Programada',   'Inspección periódica programada automáticamente',    '#17a2b8'),
            ('Inactiva',     'Inspección que fue reprogramada',                    '#6c757d'),
            ('Reprogramada', 'Modificada: fecha, inspector, tipo o periodicidad',  '#fd7e14'),
            ('Finalizada',   'Inspección realizada y cerrada',                     '#007bff')
        ON CONFLICT (nombre) DO NOTHING
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones.inspeccion (
            id_inspeccion                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            numero_inspeccion                SERIAL UNIQUE,

            id_bien_inventario               UUID NOT NULL,
            numero_finca                     VARCHAR(15) NOT NULL,

            id_tipo_inspeccion               INTEGER NOT NULL
                REFERENCES inspecciones.tipo_inspeccion(id_tipo_inspeccion) ON DELETE RESTRICT,
            id_estado_inspeccion             INTEGER NOT NULL
                REFERENCES inspecciones.estado_inspeccion(id_estado_inspeccion) ON DELETE RESTRICT,
            email_inspector                  VARCHAR(150) NOT NULL,
            fecha_programada                 DATE NOT NULL,
            fecha_realizada                  DATE,
            descripcion_tipo                 VARCHAR(255),
            requiere_programacion_automatica BOOLEAN NOT NULL DEFAULT FALSE,
            id_periodicidad                  INTEGER
                REFERENCES inspecciones.periodicidad(id_periodicidad) ON DELETE RESTRICT,
            fecha_siguiente_programacion     DATE,
            id_inspeccion_padre              UUID
                REFERENCES inspecciones.inspeccion(id_inspeccion) ON DELETE SET NULL,
            origen                           VARCHAR(10) NOT NULL DEFAULT 'WEB'
                CHECK (origen IN ('WEB', 'MOVIL')),
            es_activo                        BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_modificacion               TIMESTAMPTZ,
            creado_por                       VARCHAR(150),
            modificado_por                   VARCHAR(150)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_bien
            ON inspecciones.inspeccion(id_bien_inventario)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_finca
            ON inspecciones.inspeccion(numero_finca)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_estado
            ON inspecciones.inspeccion(id_estado_inspeccion)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_email
            ON inspecciones.inspeccion(email_inspector)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_programada
            ON inspecciones.inspeccion(fecha_programada)
            WHERE es_activo = TRUE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_inspeccion_periodica
            ON inspecciones.inspeccion(requiere_programacion_automatica, fecha_siguiente_programacion)
            WHERE requiere_programacion_automatica = TRUE AND es_activo = TRUE
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones.levantamiento_inspeccion (
            id_levantamiento           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_inspeccion              UUID NOT NULL UNIQUE
                REFERENCES inspecciones.inspeccion(id_inspeccion) ON DELETE CASCADE,
            coordenadas                VARCHAR(100),
            condicion_bien             VARCHAR(50) NOT NULL,
            estado_ocupacion           VARCHAR(50) NOT NULL,
            nombre_ocupante            VARCHAR(200),
            tipo_identificacion_ocup   VARCHAR(50),
            numero_identificacion_ocup VARCHAR(50),
            numero_contacto_ocupante   VARCHAR(50),
            comentarios_ocupante       VARCHAR(500),
            puertas                    JSONB,
            tipos_ventanas             JSONB,
            servicios_publicos         JSONB,
            distribucion_inmueble      JSONB,
            servicios_requeridos       JSONB,
            inspeccion_tecnica_req     BOOLEAN NOT NULL DEFAULT FALSE,
            tipos_inspeccion_tecnica   JSONB,
            motivacion                 TEXT,
            url_firma_inspector        VARCHAR(500),
            observaciones              TEXT,
            fecha_levantamiento        DATE NOT NULL,
            fecha_creacion             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            creado_por                 VARCHAR(150),
            CONSTRAINT chk_ocupante_datos CHECK (
                estado_ocupacion = 'Desocupado'
                OR (nombre_ocupante IS NOT NULL AND numero_contacto_ocupante IS NOT NULL)
            )
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_levantamiento_inspeccion
            ON inspecciones.levantamiento_inspeccion(id_inspeccion)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS inspecciones.inspeccion_fotografia (
            id_fotografia       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_levantamiento    UUID NOT NULL
                REFERENCES inspecciones.levantamiento_inspeccion(id_levantamiento) ON DELETE CASCADE,
            url_s3              VARCHAR(500) NOT NULL,
            nombre_archivo      VARCHAR(255),
            es_visible_geovisor BOOLEAN NOT NULL DEFAULT FALSE,
            es_foto_principal   BOOLEAN NOT NULL DEFAULT FALSE,
            orden               SMALLINT DEFAULT 0,
            fecha_creacion      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_foto_levantamiento
            ON inspecciones.inspeccion_fotografia(id_levantamiento)
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_foto_principal
            ON inspecciones.inspeccion_fotografia(id_levantamiento)
            WHERE es_foto_principal = TRUE
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspecciones.inspeccion_fotografia CASCADE")
    op.execute("DROP TABLE IF EXISTS inspecciones.levantamiento_inspeccion CASCADE")
    op.execute("DROP TABLE IF EXISTS inspecciones.inspeccion CASCADE")
    op.execute("DROP TABLE IF EXISTS inspecciones.estado_inspeccion CASCADE")
    op.execute("DROP TABLE IF EXISTS inspecciones.periodicidad CASCADE")
    op.execute("DROP TABLE IF EXISTS inspecciones.tipo_inspeccion CASCADE")
