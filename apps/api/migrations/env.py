from logging.config import fileConfig

from alembic import context
from catalogforge.config import settings
from catalogforge.models import Base
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run():
    if context.is_offline_mode():
        context.configure(
            url=settings().database_url, target_metadata=target_metadata, literal_binds=True
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(settings().database_url, poolclass=pool.NullPool)
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, include_name=include_name
            )
            with context.begin_transaction():
                context.run_migrations()


run()
