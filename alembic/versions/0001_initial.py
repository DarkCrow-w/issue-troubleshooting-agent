"""初始化排查任务和原始证据表。"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS 允许已有版本平滑接入 Alembic，不会清空历史排查数据。
    op.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            updated TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence (
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            event_id TEXT NOT NULL,
            payload JSONB NOT NULL,
            PRIMARY KEY (task_id, event_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS tasks_updated_idx ON tasks(updated)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evidence")
    op.execute("DROP TABLE IF EXISTS tasks")
