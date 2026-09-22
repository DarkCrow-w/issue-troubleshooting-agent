"""统一 JSON 日志：自动关联任务，只记录诊断元数据，不记录业务正文。"""

import json
import logging
import sys
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

_task_id = ContextVar("task_id", default=None)
logger = logging.getLogger("troubleshooter")

# 限定可输出字段，防止调用方顺手把请求、模型输出或连接串写入日志。
_ALLOWED_FIELDS = {
    "task_id",
    "stage",
    "status",
    "duration_ms",
    "count",
    "bytes_read",
    "warning_count",
    "query_number",
    "model_calls",
    "attempt",
    "input_tokens",
    "output_tokens",
    "estimated_input_tokens",
    "skill_id",
    "source_mode",
    "model_mode",
}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "event": record.msg,
            "task_id": getattr(record, "task_id", None),
            **getattr(record, "fields", {}),
        }
        error = getattr(record, "safe_error", None)
        if error:
            entry.update(error)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str = "INFO"):
    """仅配置应用 logger；禁用会反复输出完整 URL 的成功访问日志。"""
    logger.setLevel(level.upper())
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    # 业务操作由下面的事件日志覆盖；健康检查和状态轮询不重复记录。
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


@contextmanager
def task_context(task_id: str):
    """ContextVar 随异步任务隔离，退出后恢复，避免并发时串错任务。"""
    token = _task_id.set(task_id)
    try:
        yield
    finally:
        _task_id.reset(token)


def log_event(
    event: str, *, level: int = logging.INFO, error: Exception | None = None, **fields
):
    safe_fields = {
        key: value for key, value in fields.items() if key in _ALLOWED_FIELDS
    }
    extra = {"task_id": _task_id.get(), "fields": safe_fields}
    if error is not None:
        # 保留错误类型和代码位置，不输出可能包含密码/日志正文的异常消息及局部变量。
        extra["safe_error"] = {
            "error_type": type(error).__name__,
            "error_frames": [
                {
                    "file": Path(frame.filename).name,
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(error.__traceback__)[-8:]
            ],
        }
    logger.log(level, event, extra=extra)
