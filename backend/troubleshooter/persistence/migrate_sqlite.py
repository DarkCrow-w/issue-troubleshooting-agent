"""One-time, idempotent import of a stopped application's SQLite backup."""

import argparse
import json
import sqlite3
from pathlib import Path

from psycopg.types.json import Jsonb

from troubleshooter.config.settings import Settings
from troubleshooter.persistence.postgres import Store


def migrate(source: Path, store: Store) -> dict[str, int]:
    counts = {"tasks": 0, "evidence": 0}
    # Read-only source; all destination inserts commit together or roll back together.
    old = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        with store.connect() as db:
            for task_id, updated, payload in old.execute("SELECT id, updated, payload FROM tasks"):
                cursor = db.execute(
                    """INSERT INTO tasks (id, updated, payload) VALUES (%s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (task_id, updated, Jsonb(json.loads(payload))),
                )
                counts["tasks"] += cursor.rowcount
            for task_id, event_id, payload in old.execute(
                "SELECT task_id, event_id, payload FROM evidence"
            ):
                cursor = db.execute(
                    """INSERT INTO evidence (task_id, event_id, payload) VALUES (%s, %s, %s)
                       ON CONFLICT (task_id, event_id) DO NOTHING""",
                    (task_id, event_id, Jsonb(json.loads(payload))),
                )
                counts["evidence"] += cursor.rowcount
    finally:
        old.close()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Path to a SQLite backup")
    args = parser.parse_args()
    print(migrate(args.source, Store(Settings().database_url)))
