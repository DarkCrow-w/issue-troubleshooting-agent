"""Browser-facing API. Agent credentials never reach the frontend."""

from contextlib import asynccontextmanager
from logging import ERROR

import httpx
from fastapi import FastAPI, HTTPException, Response

from troubleshooter.config.settings import Settings, get_settings
from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.observability.logging import configure_logging, log_event


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=settings.agent_url,
            headers={"Authorization": "Bearer " + settings.service_token},
            timeout=15,
        ) as client:
            app.state.agent = client
            yield

    app = FastAPI(title="Transaction Troubleshooter API", lifespan=lifespan)

    async def forward(method: str, path: str, payload=None):
        try:
            response = await app.state.agent.request(method, path, json=payload)
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type="application/json",
            )
        except httpx.HTTPError as exc:
            # GET 状态轮询失败交给浏览器展示，避免故障期间每秒刷屏。
            if method != "GET":
                log_event("api.agent_unavailable", level=ERROR, error=exc)
            raise HTTPException(503, "Agent Service 暂时不可用") from None

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "api"}

    @app.get("/api/workflows")
    async def workflows():
        return await forward("GET", "/internal/workflows")

    @app.post("/api/investigations", status_code=202)
    async def create(request: InvestigationRequest):
        return await forward("POST", "/internal/investigations", request.model_dump(mode="json"))

    @app.get("/api/investigations/{task_id}")
    async def get(task_id: str):
        return await forward("GET", f"/internal/investigations/{task_id}")

    @app.post("/api/investigations/{task_id}/cancel")
    async def cancel(task_id: str):
        return await forward("POST", f"/internal/investigations/{task_id}/cancel")

    @app.get("/api/investigations/{task_id}/evidence/{event_id}")
    async def evidence(task_id: str, event_id: str):
        return await forward("GET", f"/internal/investigations/{task_id}/evidence/{event_id}")

    return app
