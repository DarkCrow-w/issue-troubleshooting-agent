"""50 组复杂交易通过真实 InvestigationService / LangGraph 工作流回归。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from scenarios import SCENARIOS, Scenario

from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.investigation.service import InvestigationService
from troubleshooter.logs.sources import ReplaySource
from troubleshooter.persistence.postgres import Store
from troubleshooter.skills import SkillRegistry


def _request(scenario: Scenario) -> InvestigationRequest:
    return InvestigationRequest(
        correlation_id=scenario.correlation_id,
        environment="demo",
        start_time=datetime.fromisoformat("2026-07-28T16:50:00+08:00"),
        end_time=datetime.fromisoformat("2026-07-28T16:55:00+08:00"),
        cleaning_enabled=scenario.cleaning_enabled,
        workflow="exceptions",
        question="定位该笔合成交易的最早失败、调用链和原因",
    )


def _service(settings, config, replay_path: Path) -> InvestigationService:
    source = ReplaySource(replay_path, config)
    return InvestigationService(
        settings,
        config,
        SkillRegistry(settings.skills_dir, config),
        source,
        Store(settings.database_url),
    )


async def _run_scenario(settings, config, tmp_path: Path, scenario: Scenario) -> tuple[dict, str]:
    replay_path = tmp_path / f"{scenario.id}.json"
    replay_path.write_text(json.dumps(scenario.records, ensure_ascii=False), encoding="utf-8")
    engine = _service(settings, config, replay_path)
    task = {"id": scenario.id, "status": "running"}
    await engine.run(task, _request(scenario), engine.store.save)
    # 用户要求保留原始数据，因此直接检查 PostgreSQL 中的证据内容。
    with engine.store.connect() as database:
        evidence = [
            row[0]
            for row in database.execute(
                "SELECT payload FROM evidence WHERE task_id = %s", (scenario.id,)
            )
        ]
    return task, json.dumps(evidence, ensure_ascii=False)


def _check(scenario: Scenario, task: dict, stored_evidence: str) -> list[str]:
    expected = scenario.expected
    report = task["report"]
    graph = report["graph"]
    failures: list[str] = []

    def expect(condition: bool, message: str):
        if not condition:
            failures.append(message)

    expect(task["status"] in {"completed", "partial"}, f"任务状态异常：{task['status']}")
    if expected.observed_events is not None:
        expect(
            report["coverage"]["observed_events"] == expected.observed_events,
            f"事件数期望 {expected.observed_events}，实际 {report['coverage']['observed_events']}",
        )
    if expected.services is not None:
        expect(
            set(graph["services"]) == expected.services,
            f"服务集合期望 {sorted(expected.services)}，实际 {graph['services']}",
        )
    if expected.node_count is not None:
        expect(
            len(graph["nodes"]) == expected.node_count,
            f"节点数期望 {expected.node_count}，实际 {len(graph['nodes'])}",
        )
    if expected.edge_count is not None:
        expect(
            len(graph["edges"]) == expected.edge_count,
            f"边数期望 {expected.edge_count}，实际 {len(graph['edges'])}",
        )

    earliest = report["earliest_observed_failure"]
    if expected.no_failure:
        expect(earliest is None, f"出现误报失败：{earliest}")
    if expected.failure_service:
        expect(earliest is not None, "未识别预期失败")
        if earliest:
            expect(
                earliest["service"] == expected.failure_service,
                f"最早失败服务期望 {expected.failure_service}，实际 {earliest['service']}",
            )
            if expected.failure_reason:
                expect(
                    expected.failure_reason in " ".join(earliest["reasons"]),
                    f"失败原因未包含 {expected.failure_reason}：{earliest['reasons']}",
                )
    if expected.warning_contains:
        expect(
            any(expected.warning_contains in warning for warning in report["warnings"]),
            f"告警未包含：{expected.warning_contains}",
        )
    if expected.unknown_contains:
        expect(
            any(expected.unknown_contains in item for item in report["unknowns"]),
            f"未知项未包含：{expected.unknown_contains}",
        )
    if expected.exception_type:
        exceptions = report["artifacts"].get("exception-analysis", {}).get("exceptions", [])
        expect(
            any(item["type"] == expected.exception_type for item in exceptions),
            f"未提取异常类型：{expected.exception_type}",
        )

    serialized = json.dumps(task, ensure_ascii=False)
    for forbidden in expected.forbidden_text:
        expect(forbidden not in serialized, f"报告或任务中出现无关文本：{forbidden[:40]}")
    for required in expected.stored_contains_text:
        expect(
            required in stored_evidence,
            f"PostgreSQL 证据未保留原始文本：{required[:40]}",
        )
    if expected.cleaning_reduced is True:
        expect(
            task["usage"]["after_chars"] < task["usage"]["before_chars"],
            f"清洗未缩减模型输入：{task['usage']}",
        )
    return failures


def test_complex_scenario_catalog_is_complete():
    assert len(SCENARIOS) == 50
    assert [scenario.number for scenario in SCENARIOS] == list(range(1, 51))
    assert len({scenario.title for scenario in SCENARIOS}) == 50


async def test_all_50_complex_scenarios_through_agent(settings, config, tmp_path):
    """跑完全部场景再统一失败，让一次执行能暴露所有独立问题。"""

    all_failures: list[str] = []
    for scenario in SCENARIOS:
        task, stored_evidence = await _run_scenario(settings, config, tmp_path, scenario)
        failures = _check(scenario, task, stored_evidence)
        all_failures.extend(f"{scenario.id} {scenario.title}: {item}" for item in failures)

    if all_failures:
        pytest.fail("复杂场景回归失败：\n" + "\n".join(all_failures))
