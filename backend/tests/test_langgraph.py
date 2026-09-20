"""Runtime regression tests: exercise real graph routing and the LangChain adapter."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_workflow import make_service, request, run

from troubleshooter.domain.models import ModelDiagnosis
from troubleshooter.investigation.budget import RunBudget
from troubleshooter.models.client import ModelClient, ModelUnavailable


@pytest.mark.parametrize("limit", [0, 1, 3])
async def test_followup_graph_repeats_extraction_within_budget(settings, config, limit):
    settings.max_followups = limit
    task = await run(make_service(settings, config), request())
    assert task["status"] == "completed"
    assert task["usage"]["followups"] <= limit
    assert task["steps"].count("retrieve") == task["usage"]["queries"]
    assert task["steps"].count("extract_request-response") == task["usage"]["queries"]
    assert task["steps"][-2:] == ["prepare_analysis", "report"]
    if limit:
        assert task["usage"]["followups"] > 0


async def test_cancel_model_preserves_collected_facts(settings, config):
    settings.model_mode = "live"
    config["workflows"]["standard"]["skills"].remove("evidence-followup")
    entered, stopped = asyncio.Event(), asyncio.Event()

    class WaitingModel:
        async def generate(self, *args):
            entered.set()
            try:
                await asyncio.sleep(100)
            finally:
                stopped.set()

    service = make_service(settings, config)
    service.model_factory = lambda settings, budget: WaitingModel()
    task = {"id": "cancel-model", "status": "running"}
    future = asyncio.create_task(service.run(task, request(), service.store.save))
    await entered.wait()
    future.cancel()
    await future
    assert stopped.is_set()
    assert task["status"] == "cancelled"
    assert len(task["report"]["graph"]["nodes"]) == 3
    assert task["report"]["findings"]
    assert service.store.get(task["id"])["status"] == "cancelled"


async def test_graph_handles_model_budget_without_losing_facts(settings, config):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    settings.model_mode = "live"
    settings.max_model_calls = 1
    service = make_service(settings, config)
    service.model_factory = lambda settings, budget: ModelClient(
        settings,
        budget,
        FakeMessagesListChatModel(responses=[AIMessage(content='{"proposals":[]}')]),
    )
    task = await run(service, request())
    assert task["status"] == "partial"
    assert task["usage"]["model_calls"] == 1
    assert task["report"]["findings"]
    assert any("预算" in item for item in task["report"]["warnings"])
    assert task["steps"][-1] == "report"


@pytest.fixture
def model_server():
    """Use a local HTTP endpoint so LangChain and the actual OpenAI SDK are exercised."""
    calls = []
    response = {"status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({"path": self.path, "body": body})
            self.send_response(response["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "id": "local-test",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "test-model",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {
                                    "role": "assistant",
                                    "content": '{"summary":"adapter works"}',
                                },
                            }
                        ],
                        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
                    }
                ).encode()
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", calls, response
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("status", [200, 500])
async def test_langchain_openai_http_contract(settings, model_server, status):
    url, calls, response = model_server
    response["status"] = status
    settings.model_mode, settings.llm_base_url = "live", url
    settings.llm_api_key, settings.llm_model = "synthetic-test-key", "test-model"
    budget = RunBudget(settings)
    client = ModelClient(settings, budget)
    try:
        if status == 200:
            result = await client.generate("Analyze", {"events": []}, ModelDiagnosis, set())
            assert result.summary == "adapter works"
            assert budget.usage.prompt_tokens == 12
            assert budget.usage.completion_tokens == 7
        else:
            with pytest.raises(ModelUnavailable, match="接口不可用"):
                await client.generate("Analyze", {}, ModelDiagnosis, set())
        assert len(calls) == 1  # Provider retries cannot bypass our invocation budget.
        assert budget.usage.model_calls == 1
        assert calls[0]["path"] == "/v1/chat/completions"
        assert calls[0]["body"]["model"] == "test-model"
        body = calls[0]["body"]
        assert (
            body.get("max_completion_tokens", body.get("max_tokens"))
            == settings.llm_max_output_tokens
        )
        assert [m["role"] for m in calls[0]["body"]["messages"]] == ["system", "user"]
    finally:
        await client.aclose()


async def test_cancel_between_chunks_keeps_completed_model_analysis(settings, config):
    from troubleshooter.domain.models import SearchResult

    settings.model_mode = "live"
    config["workflows"]["standard"]["skills"].remove("evidence-followup")
    entered = asyncio.Event()

    class LargeSource:
        async def search(self, *args):
            return SearchResult(
                records=[
                    {
                        "_time": "2026-07-28T16:51:00+08:00",
                        "app": "cm-gateway",
                        "correlationId": "demo-transaction-001",
                        "_raw": "large synthetic log" * 2000,
                    }
                ]
            )

    class PartialModel:
        calls = 0

        async def generate(self, *args):
            self.calls += 1
            if self.calls == 1:
                return ModelDiagnosis(summary="completed first chunk")
            entered.set()
            await asyncio.sleep(100)

    service = make_service(settings, config, LargeSource())
    service.model_factory = lambda settings, budget: PartialModel()
    task = {"id": "cancel-chunk", "status": "running"}
    future = asyncio.create_task(
        service.run(task, request(cleaning_enabled=False), service.store.save)
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    future.cancel()
    await future
    assert task["status"] == "cancelled"
    assert task["report"]["summary"] == "completed first chunk"
    assert task["report"]["warnings"]


async def test_client_cleanup_failure_does_not_discard_report(settings, config):
    class BrokenCleanup(ModelClient):
        async def aclose(self):
            raise RuntimeError("provider connection details must stay private")

    service = make_service(settings, config)
    service.model_factory = BrokenCleanup
    task = await run(service, request())
    assert task["status"] == "partial"
    assert task["report"]["findings"]
    assert "provider connection" not in json.dumps(task)
    assert service.store.get(task["id"])["report"] == task["report"]


async def test_truncated_model_output_is_not_accepted_as_complete(settings):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    settings.model_mode = "live"
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content='{"summary":"unfinished',
                response_metadata={"finish_reason": "length"},
                usage_metadata={"input_tokens": 10, "output_tokens": 30, "total_tokens": 40},
            )
        ]
    )
    budget = RunBudget(settings)
    with pytest.raises(ModelUnavailable, match="长度上限"):
        await ModelClient(settings, budget, model).generate("Analyze", {}, ModelDiagnosis, set())
    assert budget.usage.model_calls == 1
    assert budget.usage.completion_tokens == 30


def test_input_budget_reserves_configured_model_output(settings):
    settings.llm_context_tokens = 12000
    settings.llm_max_output_tokens = 8192
    assert RunBudget(settings).input_limit == 3808
