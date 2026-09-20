import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import yaml
from psycopg import sql
from psycopg.conninfo import make_conninfo

from troubleshooter.config.settings import PROJECT_ROOT, Settings


@pytest.fixture
def config():
    return yaml.safe_load((PROJECT_ROOT / "config/settings.yaml").read_text())


@pytest.fixture
def settings(tmp_path: Path):
    base_url = os.environ.get("TEST_DATABASE_URL") or Settings().database_url
    if not base_url:
        pytest.fail("PostgreSQL tests require DATABASE_URL or TEST_DATABASE_URL")
    schema = "test_tracelens_" + uuid4().hex
    with psycopg.connect(base_url) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield Settings(
            _env_file=None,
            database_url=make_conninfo(base_url, options=f"-c search_path={schema}"),
            data_dir=tmp_path,
            model_mode="offline",
            source_mode="replay",
        )
    finally:
        with psycopg.connect(base_url) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
