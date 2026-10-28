import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema

from app.infrastructure.config.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sqlalchemy_database_url.replace("%", "%%"))
target_metadata = None


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Limita autogenerate al schema propiedad de este microservicio."""
    if type_ == "schema":
        return name == settings.database_schema
    if type_ == "table":
        return parent_names.get("schema_name") == settings.database_schema
    return True


def configure_context(connection: Connection | None = None) -> None:
    context.configure(
        connection=connection,
        url=None if connection is not None else settings.sqlalchemy_database_url,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table="alembic_version",
        version_table_schema=settings.database_schema,
        compare_type=True,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"} if connection is None else None,
    )


def run_migrations_offline() -> None:
    configure_context()
    # En modo SQL no existe una conexión que pueda hacer el bootstrap previo.
    # Debe emitirse antes de que Alembic genere su tabla de versión.
    context.execute(f"CREATE SCHEMA IF NOT EXISTS {settings.database_schema}")
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Alembic crea su tabla de versión antes de ejecutar la primera revisión. El
    # schema debe existir para alojarla. Evitamos ejecutar CREATE SCHEMA cuando ya
    # fue provisionado por un DBA, porque PostgreSQL exige CREATE sobre la base de
    # datos incluso al usar IF NOT EXISTS.
    if not inspect(connection).has_schema(settings.database_schema):
        connection.execute(CreateSchema(settings.database_schema))
    # La introspección también inicia una transacción implícita. Debe cerrarse
    # antes de entregar la conexión al contexto transaccional de Alembic.
    connection.commit()
    configure_context(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        settings.sqlalchemy_database_url,
        connect_args={"ssl": settings.database_ssl_mode},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
