"""Internal HTTP API: authentication and transport, not task execution policy."""

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException

from troubleshooter.bootstrap import build_service
from troubleshooter.config.settings import Settings, get_settings
from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.investigation.tasks import TaskManager
from troubleshooter.logs.sources import spl_literal
from troubleshooter.observability.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    service = build_service(settings)
    manager = TaskManager(service)

    @asynccontextmanager
    async def lifespan(app):
        await manager.start()
        yield
        await manager.close()

    app = FastAPI(title="Transaction Agent Service", lifespan=lifespan)
    app.state.store, app.state.service, app.state.tasks = service.store, service, manager

    async def authenticate(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, "Bearer " + settings.service_token):
            raise HTTPException(401, "内部服务认证失败")

    dependencies = [Depends(authenticate)]

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "agent"}

    @app.get("/internal/workflows", dependencies=dependencies)
    async def workflows():
        return {
            "workflows": [{"id": k, **v} for k, v in service.config["workflows"].items()],
            "environments": list(service.config["environments"]),
            "source_mode": settings.source_mode,
            "model_mode": settings.model_mode,
            "model": settings.llm_model,
        }

    @app.post("/internal/investigations", status_code=202, dependencies=dependencies)
    async def create(request: InvestigationRequest):
        try:
            service.registry.workflow(request.workflow)
            spl_literal(request.correlation_id)
            if request.environment not in service.config["environments"]:
                raise ValueError("未知环境")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return manager.submit(request)

    @app.get("/internal/investigations/{task_id}", dependencies=dependencies)
    async def get(task_id: str):
        task = service.store.get(task_id)
        if not task:
            raise HTTPException(404, "任务不存在或已过期")
        return task

    @app.post("/internal/investigations/{task_id}/cancel", dependencies=dependencies)
    async def cancel(task_id: str):
        result = await manager.cancel(task_id)
        if result is None:
            raise HTTPException(404, "任务不存在或已过期")
        return result

    @app.get("/internal/investigations/{task_id}/evidence/{event_id}", dependencies=dependencies)
    async def evidence(task_id: str, event_id: str):
        await get(task_id)
        record = service.store.evidence(task_id, event_id)
        if not record:
            raise HTTPException(404, "证据不存在或已过期")
        return record

    return app
