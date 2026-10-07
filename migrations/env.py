import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from loyalty_service.config import Settings
from loyalty_service.models import Base

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata
# A dedicated override lets migration tests use their disposable DB.
url = os.getenv('MIGRATION_DATABASE_URL') or Settings().database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    provided_connection = config.attributes.get('connection')
    if provided_connection is not None:
        context.configure(connection=provided_connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(url, poolclass=pool.NullPool)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()
