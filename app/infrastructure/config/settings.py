from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Configuración centralizada cargada desde el entorno o un archivo .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ms-inspecciones"
    environment: str = "local"
    log_level: str = "INFO"

    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "Caja"
    database_user: str = "postgres"
    database_password: str = Field(default="", repr=False)
    database_schema: Literal["inspecciones"] = "inspecciones"

    database_pool_min_size: int = Field(default=1, ge=1)
    database_pool_max_size: int = Field(default=10, ge=1)
    database_connect_timeout: float = Field(default=5.0, gt=0)
    # Modo SSL para asyncpg: disable/allow/prefer/require/verify-ca/verify-full.
    # Aurora/RDS suele rechazar conexiones sin cifrar (pg_hba "no encryption"), por lo
    # que en despliegues contra Aurora debe forzarse "require" vía variable de entorno.
    database_ssl_mode: str = "prefer"

    # Microsoft Entra ID / Azure AD
    azure_tenant_id: str = ""
    azure_backend_client_id: str = ""
    azure_backend_client_secret: str = Field(default="", repr=False)

    # Modo local: relajar validaciones de autenticación
    is_local: bool = False

    # Endpoint directo de levantamiento (provisional, mientras no exista sincronización offline)
    enable_direct_levantamiento_endpoint: bool = False

    # Webhook de ms-requerimientos (órdenes de servicio) notificado al finalizar un
    # levantamiento con servicios_requeridos y/o inspección técnica. Vacío = deshabilitado
    # (no se llama, solo se loguea que se omitió).
    ordenes_servicio_webhook_url: str = ""
    ordenes_servicio_webhook_timeout: float = Field(default=10.0, gt=0)

    # Sincronización offline (HU.12) con AWS Batch. Con SINCRONIZACION_HABILITADA=false (por
    # ejemplo en un entorno sin la infraestructura desplegada) los endpoints nuevos responden 503
    # sin tocar AWS. Los clientes boto3 se crean al usarse, nunca al arrancar.
    sincronizacion_habilitada: bool = False
    aws_region: str = "us-east-1"
    sincronizacion_batch_job_queue: str = ""
    sincronizacion_batch_job_definition: str = ""
    sincronizacion_s3_bucket: str = ""
    sincronizacion_cloudfront_domain: str = ""
    # Etapa 1: false = la URL de descarga es la de CloudFront sin firmar (la distribución no
    # exige URL firmada). Etapa 3 la vuelve a activar junto con la seguridad por dispositivo.
    # Debe coincidir con la variable `urls_firmadas` de infra/sincronizacion-aws.
    sincronizacion_url_firmada: bool = False
    sincronizacion_cloudfront_key_pair_id: str = ""
    # Nombre del parámetro SSM (SecureString) con la clave privada RSA que firma las URLs.
    sincronizacion_cloudfront_private_key_param: str = ""
    sincronizacion_url_ttl_segundos: int = Field(default=120, ge=30, le=900)
    sincronizacion_job_ttl_horas: int = Field(default=24, ge=1)
    # Ventana máxima de espera de un GET /sincronizacion/{job_id} (long polling); debe quedar
    # por debajo del idle timeout del balanceador (ALB 60 s por defecto).
    sincronizacion_long_polling_max_segundos: int = Field(default=25, ge=1, le=50)
    # Capa de fincas (fincas.pmtiles) que el job de descarga agrega al ZIP con tippecanoe.
    sincronizacion_pmtiles_habilitado: bool = True
    sincronizacion_tippecanoe_bin: str = "tippecanoe"
    # Rutas óptimas por fecha (capa `rutas` y `rutas_optimas`). Vacío = sin rutas.
    # Ej.: http://172.31.x.x:5000 (EC2 de OSRM en la misma VPC que el job).
    osrm_url: str = ""
    osrm_timeout_segundos: float = Field(default=10.0, gt=0, le=60)

    # Subida de levantamientos por ZIP (Etapa 2 de HU.12). Comparte habilitación, región, cola de
    # Batch y límite de long polling con la descarga; el resto es propio de la subida.
    subida_batch_job_definition: str = ""
    # Bucket temporal donde la app deja el .zip (URL prefirmada) y bucket permanente de fotos.
    subida_s3_bucket: str = ""
    fotos_s3_bucket: str = ""
    # Dominio de CloudFront delante del bucket de fotos. La BD guarda solo la clave S3; la API
    # arma (y firma) la URL al devolver el detalle. Comparte key pair y clave privada con la
    # descarga (SINCRONIZACION_CLOUDFRONT_*). Debe coincidir con `fotos_urls_firmadas` de infra.
    fotos_cloudfront_domain: str = ""
    fotos_url_firmada: bool = False
    fotos_url_ttl_segundos: int = Field(default=900, ge=30, le=86400)
    subida_url_ttl_segundos: int = Field(default=900, ge=60, le=3600)
    subida_job_ttl_horas: int = Field(default=168, ge=1)
    subida_max_bytes: int = Field(default=200 * 1024 * 1024, gt=0)
    subida_max_levantamientos: int = Field(default=500, ge=1)
    subida_max_fotos_por_levantamiento: int = Field(default=30, ge=0)
    subida_max_bytes_por_imagen: int = Field(default=10 * 1024 * 1024, gt=0)

    # Prefijo montado delante de todas las rutas (health, inspecciones, notificaciones, jobs...).
    # Vacío = sin prefijo. Si no está vacío debe empezar con "/" y no terminar en "/".
    api_prefix: str = "/v1/inspeccion"

    @field_validator("api_prefix")
    @classmethod
    def _normalizar_api_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not value.startswith("/"):
            raise ValueError('API_PREFIX debe empezar con "/" o estar vacío')
        return value.rstrip("/")

    @property
    def sqlalchemy_database_url(self) -> str:
        """URL para Alembic; la aplicación se conecta con parámetros asyncpg."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.database_user,
            password=self.database_password,
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
