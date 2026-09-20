import json
import sqlite3

import psycopg
import pytest

from troubleshooter.persistence.migrate_sqlite import migrate
from troubleshooter.persistence.postgres import Store


def legacy_database(path, orphan=False):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE tasks (id TEXT PRIMARY KEY, updated TEXT, payload TEXT);
            CREATE TABLE evidence (task_id TEXT, event_id TEXT, payload TEXT);
        """)
        db.execute(
            "INSERT INTO tasks VALUES (?, ?, ?)",
            ("old", "2026-09-16T00:00:00+00:00", json.dumps({"id": "old", "status": "completed"})),
        )
        db.execute(
            "INSERT INTO evidence VALUES (?, ?, ?)",
            ("missing" if orphan else "old", "ev1", json.dumps({"message": "原始日志"})),
        )


def test_migration_preserves_json_and_does_not_overwrite_existing_tasks(settings, tmp_path):
    path = tmp_path / "legacy.db"
    legacy_database(path)
    store = Store(settings.database_url)
    assert migrate(path, store) == {"tasks": 1, "evidence": 1}
    assert store.evidence("old", "ev1") == {"message": "原始日志"}
    task = store.get("old")
    task["status"] = "partial"
    store.save(task)
    assert migrate(path, store) == {"tasks": 0, "evidence": 0}
    assert store.get("old")["status"] == "partial"
    with store.connect() as db:
        assert db.execute("SELECT pg_typeof(payload)::text FROM tasks").fetchone()[0] == "jsonb"


def test_invalid_migration_rolls_back_all_imported_rows(settings, tmp_path):
    path = tmp_path / "orphan.db"
    legacy_database(path, orphan=True)
    store = Store(settings.database_url)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        migrate(path, store)
    assert store.get("old") is None
