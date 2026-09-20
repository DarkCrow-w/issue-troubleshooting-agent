"""PostgreSQL task and original evidence storage."""

from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.types.json import Jsonb


class Store:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("请在 .env 中配置 DATABASE_URL（PostgreSQL）")
        self.database_url = database_url
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    updated TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS evidence (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    event_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    PRIMARY KEY (task_id, event_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS tasks_updated_idx ON tasks(updated)")

    def connect(self):
        # Context manager commits on success, rolls back on failure and closes the connection.
        return psycopg.connect(self.database_url, connect_timeout=5)

    def save(self, task: dict):
        """UPSERT 保证同一任务的状态更新不会产生重复记录。"""
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                """INSERT INTO tasks (id, updated, payload) VALUES (%s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET updated=EXCLUDED.updated, payload=EXCLUDED.payload""",
                (task["id"], task["updated_at"], Jsonb(task)),
            )

    def get(self, task_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM tasks WHERE id=%s", (task_id,)).fetchone()
        return row[0] if row else None

    def evidence(self, task_id: str, event_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM evidence WHERE task_id=%s AND event_id=%s",
                (task_id, event_id),
            ).fetchone()
        return row[0] if row else None

    def save_evidence(self, task_id: str, event_id: str, payload: dict):
        with self.connect() as db:
            db.execute(
                """INSERT INTO evidence (task_id, event_id, payload) VALUES (%s, %s, %s)
                   ON CONFLICT (task_id, event_id) DO UPDATE SET payload=EXCLUDED.payload""",
                (task_id, event_id, Jsonb(payload)),
            )

    def recover(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM tasks WHERE payload->>'status' IN ('queued', 'running') FOR UPDATE"
            ).fetchall()
            for (task,) in rows:
                task.update(status="failed", phase="服务重启，任务中断；请重新提交")
                task["updated_at"] = datetime.now(timezone.utc).isoformat()
                db.execute(
                    "UPDATE tasks SET updated=%s, payload=%s WHERE id=%s",
                    (task["updated_at"], Jsonb(task), task["id"]),
                )

        return len(rows)

    def purge(self, hours: int):
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self.connect() as db:
            # Foreign key cascade removes evidence in the same transaction.
            return db.execute("DELETE FROM tasks WHERE updated < %s", (threshold,)).rowcount
