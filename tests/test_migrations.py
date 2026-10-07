import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from loyalty_service.models import Base


@pytest.mark.postgres
def test_migration_upgrade_matches_models_and_downgrade():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL not set')
    engine = create_engine(url)
    schema = 'loyalty_migration_'+uuid4().hex
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}"'))
        connection.commit()
        cfg = Config('alembic.ini')
        cfg.attributes['connection'] = connection
        try:
            command.upgrade(cfg, 'head')
            command.check(cfg)
            tables = set(inspect(connection).get_table_names(schema=schema))
            assert set(Base.metadata.tables) <= tables
            command.downgrade(cfg, 'base')
            assert set(inspect(connection).get_table_names(schema=schema)) == {'alembic_version'}
            connection.commit()
        finally:
            connection.rollback()
            connection.execute(text('SET search_path TO public'))
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.commit()
    engine.dispose()
