from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.database.bases import TenantBase
from app.tenancy.schema import validate_schema_name
import app.models.tenant_template  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = TenantBase.metadata


def _tenant_schema() -> str:
    # Direct Alembic invocations (for example, a one-off provisioning or
    # migration run from PowerShell) cannot pass ``config.attributes`` like
    # the in-process provisioning runner does.  Accept the explicit ``-x
    # tenant_schema=shop_<id>`` argument as the equivalent safe input.
    value = config.attributes.get("tenant_schema")
    if not value:
        value = context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema Alembic attribute is required")
    return validate_schema_name(str(value))


def _configure(connection=None, *, url=None) -> None:
    schema = _tenant_schema()
    kwargs = {
        "target_metadata": target_metadata,
        "version_table": "alembic_version",
        "version_table_schema": schema,
        "include_schemas": True,
    }
    if connection is not None:
        context.configure(connection=connection, **kwargs)
    else:
        context.configure(
            url=url,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            **kwargs,
        )


def run_migrations_offline() -> None:
    _configure(url=settings.tenant_database_url)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        _configure(supplied_connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    config.set_main_option("sqlalchemy.url", settings.tenant_database_url.replace("%", "%%"))
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
