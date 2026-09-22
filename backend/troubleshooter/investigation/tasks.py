"""Single-instance task scheduling, cancellation and retention, independent of HTTP."""

import asyncio
from contextlib import suppress
from logging import ERROR
from uuid import uuid4

from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.observability.logging import log_event

from .service import InvestigationService


class TaskManager:
    def __init__(self, service: InvestigationService):
        self.service, self.store = service, service.store
        self.running: dict[str, asyncio.Task] = {}
        self.queue = asyncio.Semaphore(1)
        self.cleaner: asyncio.Task | None = None

    async def start(self):
        recovered = self.store.recover()
        log_event("service.started", count=recovered)
        self.cleaner = asyncio.create_task(self._cleanup())

    async def close(self):
        if self.cleaner:
            self.cleaner.cancel()
        pending = list(self.running.values())
        for future in pending:
            future.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if self.cleaner:
            with suppress(asyncio.CancelledError):
                await self.cleaner

    async def _cleanup(self):
        failed = False
        while True:
            try:
                removed = self.store.purge(self.service.settings.retention_hours)
                if removed:
                    log_event("retention.deleted", count=removed)
                if failed:
                    log_event("retention.recovered")
                failed = False
            except Exception as exc:  # noqa: BLE001
                # 持续故障仅记录第一次，恢复后再记录；清理线程继续运行。
                if not failed:
                    log_event("retention.failed", level=ERROR, error=exc)
                failed = True
            await asyncio.sleep(60)

    def submit(self, request: InvestigationRequest) -> dict:
        task = {
            "id": str(uuid4()),
            "status": "queued",
            "phase": "等待执行",
            "usage": {},
            "request": request.model_dump(mode="json"),
            "report": None,
        }
        self.store.save(task)
        log_event("task.queued", task_id=task["id"])
        future = asyncio.create_task(self._execute(task, request))
        self.running[task["id"]] = future
        future.add_done_callback(lambda _: self.running.pop(task["id"], None))
        return {"id": task["id"], "status": "queued"}

    async def _execute(self, task: dict, request: InvestigationRequest):
        try:
            async with self.queue:
                task.update(status="running", phase="准备排查")
                self.store.save(task)
                await self.service.run(task, request, self.store.save)
        except asyncio.CancelledError:
            task.update(status="cancelled", phase="任务已取消")
            self.store.save(task)

    async def cancel(self, task_id: str) -> dict | None:
        task = self.store.get(task_id)
        if task is None:
            return None
        future = self.running.get(task_id)
        if not future:
            return {"id": task_id, "status": task["status"]}
        log_event("task.cancel_requested", task_id=task_id)
        future.cancel()
        await asyncio.gather(future, return_exceptions=True)
        task = self.store.get(task_id)
        # 尚未开始执行的协程不会进入内部收尾逻辑，因此这里补存取消状态。
        if task["status"] in ("queued", "running"):
            task.update(status="cancelled", phase="任务已取消")
            self.store.save(task)
        return {"id": task_id, "status": task["status"]}
