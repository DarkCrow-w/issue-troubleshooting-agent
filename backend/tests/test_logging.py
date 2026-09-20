"""日志契约：任务关联、敏感数据隔离，以及重复故障不刷屏。"""

import asyncio
import io
import json
import logging

import pytest
from test_workflow import make_service, request, run

from troubleshooter.investigation.tasks import TaskManager
from troubleshooter.observability.logging import JsonFormatter, log_event, logger, task_context


@pytest.fixture
def log_output():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield stream
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def entries(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_safe_error_contains_location_but_never_exception_body(log_output):
    try:
        raise ValueError("secret-password-and-private-log")
    except ValueError as exc:
        with task_context("task-safe"):
            log_event("test.failed", level=logging.ERROR, error=exc, payload="private payload")
    event = entries(log_output)[0]
    assert event["task_id"] == "task-safe"
    assert event["error_type"] == "ValueError"
    assert event["error_frames"][0]["file"] == "test_logging.py"
    assert "secret-password" not in log_output.getvalue()
    assert "private payload" not in log_output.getvalue()
    assert "timestamp" in event


async def test_async_task_contexts_do_not_leak(log_output):
    async def emit(task_id):
        with task_context(task_id):
            await asyncio.sleep(0)
            log_event("test.context")

    await asyncio.gather(emit("first"), emit("second"))
    log_event("test.outside")
    assert [entry["task_id"] for entry in entries(log_output)] == ["first", "second", None]


async def test_real_graph_logs_share_task_id_without_business_payload(settings, config, log_output):
    task = await run(make_service(settings, config), request())
    records = entries(log_output)
    assert records[0]["event"] == "task.started"
    assert records[-1]["event"] == "task.finished"
    assert records[-1]["status"] == "completed"
    assert all(record["task_id"] == task["id"] for record in records)
    assert (
        len([record for record in records if record["event"] == "query.completed"])
        == task["usage"]["queries"]
    )
    assert "demo-transaction-001" not in log_output.getvalue()
    assert "demo-secret-never-real" not in log_output.getvalue()
    assert not any(record["event"].startswith("graph.") for record in records)


async def test_cleanup_logs_failure_once_and_then_recovery(
    settings, config, log_output, monkeypatch
):
    manager = TaskManager(make_service(settings, config))
    attempts = 0

    def purge(hours):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise RuntimeError("private connection details")
        return 0

    async def sleep(seconds):
        if attempts == 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(manager.store, "purge", purge)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await manager._cleanup()
    assert [row["event"] for row in entries(log_output)] == [
        "retention.failed",
        "retention.recovered",
    ]
