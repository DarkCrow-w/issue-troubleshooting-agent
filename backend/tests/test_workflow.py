import asyncio
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from troubleshooter.api.agent import create_app
from troubleshooter.domain.models import (
    FollowupProposal,
    InvestigationRequest,
    QuerySpec,
    SearchResult,
)
from troubleshooter.investigation.service import InvestigationService
from troubleshooter.logs.sources import ReplaySource, build_spl
from troubleshooter.persistence.postgres import Store
from troubleshooter.skills import SkillRegistry


def request(**changes):
    values = {
        "correlation_id": "demo-transaction-001",
        "environment": "demo",
        "start_time": datetime.fromisoformat("2026-07-28T16:50:00+08:00"),
        "end_time": datetime.fromisoformat("2026-07-28T16:55:00+08:00"),
    }
    values.update(changes)
    return InvestigationRequest(**values)


def make_service(settings, config, source=None):
    registry = SkillRegistry(settings.skills_dir, config)
    store = Store(settings.database_url)
    return InvestigationService(
        settings, config, registry, source or ReplaySource(settings.replay_path, config), store
    )


async def run(engine, req):
    task = {"id": "test", "status": "running"}
    await engine.run(task, req, engine.store.save)
    return task


@pytest.mark.parametrize("cleaning", [True, False])
async def test_replay_end_to_end(settings, config, cleaning):
    task = await run(make_service(settings, config), request(cleaning_enabled=cleaning))
    report = task["report"]
    assert task["status"] == "completed"
    assert report["findings"]
    assert report["earliest_observed_failure"]["service"] == "cm-acct-scene"
    assert len(report["graph"]["edges"]) == 2
    assert len(report["graph"]["nodes"]) == 3
    assert task["usage"]["followups"] <= 3
    assert "another-transaction" not in json.dumps(report["graph"])
    assert "demo-secret-never-real" not in json.dumps(task)
    assert task["snapshot"]["skills"]
    assert all(n["evidence_ids"] for n in report["graph"]["nodes"])


async def test_cleaning_keeps_failure_facts(settings, config):
    engine = make_service(settings, config)
    clean = await run(engine, request(cleaning_enabled=True))
    raw = await run(engine, request(cleaning_enabled=False))
    assert clean["report"]["findings"] == raw["report"]["findings"]
    assert clean["usage"]["after_chars"] < raw["usage"]["after_chars"]


async def test_followup_rejects_invented_ids_and_scope(settings, config):
    from troubleshooter.investigation.followups import validate_proposal
    from troubleshooter.investigation.state import initial_state

    engine = make_service(settings, config)
    task = await run(engine, request())
    event_id = task["report"]["graph"]["nodes"][0]["evidence_ids"][0]
    from troubleshooter.domain.models import Event

    event = Event(**engine.store.evidence("test", event_id)["event"])
    state = initial_state(request())
    state["events"][event.id] = event
    assert (
        validate_proposal(
            FollowupProposal(
                kind="identifier", evidence_id=event.id, identifier="made-up", reason="test"
            ),
            state,
            request(),
        )
        is None
    )
    query = validate_proposal(
        FollowupProposal(kind="context", evidence_id=event.id, reason="test"), state, request()
    )
    assert query.environment == "demo"
    assert request().start_time <= query.start_time < query.end_time <= request().end_time
    assert (query.end_time - query.start_time).total_seconds() <= 4


async def test_budget_and_timeout_keep_partial_facts(settings, config):
    settings.max_events = 2
    task = await run(make_service(settings, config), request())
    assert task["status"] == "partial"
    assert task["usage"]["events"] <= 2
    assert task["report"]["warnings"]

    class SlowSource:
        async def search(self, *args):
            await asyncio.sleep(3)
            return SearchResult()

    settings.task_timeout_seconds = 1
    task = await run(make_service(settings, config, SlowSource()), request())
    assert task["status"] == "partial"
    assert any("时间上限" in w for w in task["report"]["warnings"])


def test_skill_registry_validation_and_custom_llm(settings, config, tmp_path):
    import shutil

    import yaml

    directory = tmp_path / "skills"
    shutil.copytree(settings.skills_dir, directory)
    custom = directory / "business-error"
    custom.mkdir()
    metadata = {
        "id": "business-error",
        "version": "1",
        "description": "custom",
        "kind": "llm",
        "depends_on": ["failure-localization"],
        "tools": [],
        "output": "evidence-claims",
    }
    (custom / "skill.yaml").write_text(yaml.safe_dump(metadata))
    (custom / "prompt.md").write_text("Explain configured business codes.")
    config["workflows"]["standard"]["skills"].insert(-1, "business-error")
    registry = SkillRegistry(directory, config)
    assert any(s.id == "business-error" for s in registry.workflow("standard"))
    metadata["depends_on"] = ["business-error"]
    (custom / "skill.yaml").write_text(yaml.safe_dump(metadata))
    with pytest.raises(ValueError, match="循环"):
        SkillRegistry(directory, config)


def test_spl_injection_and_environment_restrictions(config):
    spec = QuerySpec(
        **request().model_dump(
            exclude={"correlation_id", "cleaning_enabled", "workflow", "question"}
        ),
        identifier='abc" | delete | search "xyz',
    )
    spl = build_spl(spec, config)
    assert '\\" | delete' in spl
    spec.identifier = "*"
    with pytest.raises(ValueError):
        build_spl(spec, config)
    spec.identifier = "abc"
    spec.environment = "not-configured"
    with pytest.raises(ValueError):
        build_spl(spec, config)


def test_optional_time_and_custom_spl(config):
    custom = request(
        correlation_id="",
        spl='search correlationId="demo-transaction-001" | fields _time appName message',
        start_time=None,
        end_time=None,
    )
    spec = QuerySpec(
        environment=custom.environment,
        start_time=custom.start_time,
        end_time=custom.end_time,
        spl=custom.spl,
    )

    spl = build_spl(spec, config)

    assert 'index="demo_transactions"' in spl
    assert '(correlationId="demo-transaction-001")' in spl
    assert spl.endswith("| fields _time appName message")
    with pytest.raises(ValueError, match="至少填写一个"):
        request(correlation_id="", spl="")
    with pytest.raises(ValueError, match="不允许"):
        build_spl(QuerySpec(environment="demo", spl="| outputlookup unsafe.csv"), config)


async def test_replay_without_time_window(settings, config):
    task = await run(
        make_service(settings, config),
        request(start_time=None, end_time=None),
    )

    assert task["status"] == "completed"
    assert task["report"]["coverage"]["observed_events"] > 0
    assert task["report"]["queries"][0]["start_time"] is None
    assert task["report"]["queries"][0]["end_time"] is None


async def test_replay_supports_exact_id_in_custom_spl(settings, config):
    task = await run(
        make_service(settings, config),
        request(
            correlation_id="",
            spl='search correlationId="demo-transaction-001" | fields _time appName message',
            start_time=None,
            end_time=None,
        ),
    )

    serialized_graph = json.dumps(task["report"]["graph"])
    assert "demo-transaction-001" not in serialized_graph
    assert "another-transaction" not in serialized_graph
    assert task["report"]["coverage"]["observed_events"] > 0
    assert any("回放模式仅模拟" in warning for warning in task["report"]["warnings"])


def test_api_validation_evidence_and_restart(settings):
    app = create_app(settings)
    headers = {"Authorization": "Bearer " + settings.service_token}
    with TestClient(app) as client:
        assert client.get("/internal/workflows").status_code == 401
        payload = request().model_dump(mode="json")
        invalid = {**payload, "end_time": payload["start_time"]}
        assert (
            client.post("/internal/investigations", json=invalid, headers=headers).status_code
            == 422
        )
        response = client.post("/internal/investigations", json=payload, headers=headers)
        assert response.status_code == 202
        task_id = response.json()["id"]
        import time

        for _ in range(30):
            task = client.get("/internal/investigations/" + task_id, headers=headers).json()
            if task["status"] not in ("queued", "running"):
                break
            time.sleep(0.02)
        assert task["status"] == "completed"
        evidence_id = task["report"]["findings"][0]["evidence_ids"][0]
        evidence = client.get(
            f"/internal/investigations/{task_id}/evidence/{evidence_id}", headers=headers
        )
        assert evidence.status_code == 200
        assert "event" in evidence.json()
        assert (
            client.get(
                f"/internal/investigations/{task_id}/evidence/missing", headers=headers
            ).status_code
            == 404
        )
    app.state.store.save({"id": "interrupted", "status": "running"})
    with TestClient(create_app(settings)) as client:
        assert (
            client.get("/internal/investigations/interrupted", headers=headers).json()["status"]
            == "failed"
        )


async def test_cancel_stops_source(settings, config):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class WaitingSource:
        async def search(self, *args):
            entered.set()
            try:
                await asyncio.sleep(100)
            finally:
                cancelled.set()

    engine = make_service(settings, config, WaitingSource())
    task = {"id": "cancel", "status": "running"}
    future = asyncio.create_task(engine.run(task, request(), engine.store.save))
    await entered.wait()
    future.cancel()
    await future
    assert cancelled.is_set()
    assert task["status"] == "cancelled"


async def test_context_events_are_not_transaction_calls(settings, config):
    from troubleshooter.domain.models import Event
    from troubleshooter.investigation.followups import validate_proposal
    from troubleshooter.investigation.state import initial_state

    engine = make_service(settings, config)
    task = await run(engine, request())
    with engine.store.connect() as db:
        records = [row[0] for row in db.execute("SELECT payload FROM evidence")]
    context = [Event(**row["event"]) for row in records if row["event"]["scope"] == "context"]
    assert len(context) == 1
    assert context[0].correlation_ids == ["another-transaction"]
    assert context[0].id not in [e["event_id"] for e in task["report"]["graph"]["timeline"]]
    state = initial_state(request())
    state["events"][context[0].id] = context[0]
    assert (
        validate_proposal(
            FollowupProposal(
                kind="identifier",
                evidence_id=context[0].id,
                identifier="another-transaction",
                reason="wrong transaction",
            ),
            state,
            request(),
        )
        is None
    )


async def test_custom_skill_composition_and_evidence_expansion(settings, config):
    from troubleshooter.domain.models import ModelDiagnosis
    from troubleshooter.skills import Skill

    settings.model_mode = "live"
    engine = make_service(settings, config)
    custom = Skill(
        id="business-error",
        version="1",
        description="custom",
        kind="llm",
        output="evidence-claims",
        depends_on=["failure-localization"],
        prompt="CUSTOM",
    )
    engine.registry.skills[custom.id] = custom
    config["workflows"]["standard"]["skills"].insert(-1, custom.id)
    config["workflows"]["standard"]["skills"].remove("evidence-followup")
    calls = []

    class FakeModel:
        async def generate(self, prompt, payload, schema, valid_ids):
            calls.append(payload)
            event_id = sorted(valid_ids)[0]
            if prompt == "CUSTOM":
                return ModelDiagnosis(
                    summary="custom knowledge",
                    findings=[
                        {
                            "statement": "custom interpretation",
                            "evidence_ids": [event_id],
                            "confidence": "low",
                        }
                    ],
                )
            if "requested_evidence" in payload:
                assert payload["requested_evidence"][0]["event_id"] == event_id
                return ModelDiagnosis(
                    summary="expanded conclusion",
                    findings=[
                        {
                            "statement": "expanded interpretation",
                            "evidence_ids": [event_id],
                            "confidence": "low",
                        }
                    ],
                )
            assert "business-error" in payload["prior_skill_artifacts"]
            return ModelDiagnosis(summary="need detail", evidence_requests=[event_id])

    engine.model_factory = lambda settings, budget: FakeModel()
    task = await run(engine, request())
    assert task["status"] == "completed"
    assert task["report"]["summary"] == "expanded conclusion"
    assert len(calls) == 3
    assert "business-error" in task["report"]["artifacts"]
    assert task["steps"].count("analyse_chunk") == 2
    assert task["steps"].count("finish_skill") == 2


def test_retention_removes_expired_evidence(settings):
    store = Store(settings.database_url)
    store.save({"id": "old", "status": "completed"})
    store.save_evidence("old", "ev1", {"record": "redacted"})
    with store.connect() as db:
        db.execute("UPDATE tasks SET updated='2000-01-01T00:00:00+00:00' WHERE id='old'")
    store.purge(24)
    assert store.get("old") is None
    assert store.evidence("old", "ev1") is None


async def test_no_logs_is_explicitly_partial(settings, config):
    class EmptySource:
        async def search(self, *args):
            return SearchResult()

    task = await run(make_service(settings, config, EmptySource()), request())
    assert task["status"] == "partial"
    assert task["report"]["coverage"]["observed_events"] == 0
    assert task["report"]["warnings"]


async def test_identical_occurrences_are_preserved(settings, config):
    class DuplicateSource:
        async def search(self, *args):
            row = {
                "_time": "2026-07-28T16:51:00+08:00",
                "app": "cm-gateway",
                "correlationId": "demo-transaction-001",
                "eventType": "request",
            }
            return SearchResult(records=[row, dict(row)])

    task = await run(make_service(settings, config, DuplicateSource()), request())
    nodes = task["report"]["graph"]["nodes"]
    assert len(nodes) == 2
    assert nodes[0]["id"] != nodes[1]["id"]


async def test_code_skill_failure_preserves_task_result(settings, config, monkeypatch):
    from troubleshooter.analysis import HANDLERS

    def broken(*args):
        raise RuntimeError("a secret must not be copied to the report")

    monkeypatch.setitem(HANDLERS, "request_response", broken)
    task = await run(make_service(settings, config), request())
    assert task["status"] == "partial"
    assert task["report"]["warnings"]
    assert "a secret" not in json.dumps(task)


async def test_success_sample_has_no_false_failure(settings, config):
    settings.replay_path = settings.replay_path.with_name("success.json")
    req = request().model_copy(update={"correlation_id": "demo-success-001"})
    task = await run(make_service(settings, config), req)
    assert task["status"] == "completed"
    assert task["report"]["findings"] == []
    assert len(task["report"]["graph"]["nodes"]) == 3
    assert len(task["report"]["graph"]["edges"]) == 2
    assert not task["report"]["earliest_observed_failure"]
