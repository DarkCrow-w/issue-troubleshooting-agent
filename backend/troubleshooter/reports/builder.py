"""Build the report from collected facts; usable after success, failure or cancellation."""

from troubleshooter.investigation.state import InvestigationState

from .markdown import render_markdown

EMPTY_GRAPH = {"nodes": [], "edges": [], "timeline": [], "services": []}
EMPTY_JOURNEY = {"stages": [], "attribution": {}, "caution": "交易链路尚未生成"}


def _model_sections(state: InvestigationState) -> tuple[list, list, list, list]:
    findings, hypotheses, unknowns, next_steps = [], [], [], []
    for diagnosis in state["diagnoses"]:
        findings.extend(c.model_dump() for c in diagnosis.findings)
        hypotheses.extend(c.model_dump() for c in diagnosis.hypotheses)
        unknowns.extend(diagnosis.unknowns)
        next_steps.extend(diagnosis.next_steps)
    return findings, hypotheses, unknowns, next_steps


def _fallback_sections(failures: list[dict]) -> tuple[list, list, list]:
    findings = [
        {
            "statement": f"{failure['service']}：" + "；".join(failure["reasons"]),
            "evidence_ids": [failure["event_id"]],
            "confidence": "high",
        }
        for failure in failures
    ]
    if not failures:
        return findings, [], []
    return (
        findings,
        ["现有规则只能确认失败信号，无法确认最终根因与异常传播关系"],
        ["检查失败事件的完整异常链和下游响应，验证根因假设"],
    )


def _graph_unknowns(graph: dict) -> list[str]:
    unknowns = []
    for node in graph["nodes"]:
        if node.get("missing_response"):
            unknowns.append(
                f"{node['service']} {node['api']} 未找到可配对响应（{node['id']}）"
            )
    if len(graph["services"]) > 1 and not graph["edges"]:
        unknowns.append("日志覆盖多个服务，但缺少足够证据建立调用关系")
    return unknowns


def _summary(state: InvestigationState, graph: dict, failures: list[dict]) -> str:
    summaries = [d.summary for d in state["diagnoses"]]
    if summaries:
        return "\n".join(summaries)
    if failures:
        return (
            f"在 {len(graph['services'])} 个服务中发现 {len(failures)} 个失败信号；"
            "根因尚未确认。"
        )
    return "未发现明确失败信号；这不证明交易已成功。"


def build_report(state: InvestigationState) -> dict:
    failure = state["artifacts"].get("failure-localization", {})
    failures = failure.get("failures", [])
    graph = state["artifacts"].get("trace-reconstruction", EMPTY_GRAPH)
    journey = state["artifacts"].get("transaction-journey", EMPTY_JOURNEY)
    findings, hypotheses, unknowns, next_steps = _model_sections(state)
    if not state["diagnoses"]:
        findings, unknowns, next_steps = _fallback_sections(failures)
    unknowns.extend(_graph_unknowns(graph))

    report = {
        "summary": _summary(state, graph, failures),
        "graph": graph,
        "journey": journey,
        "findings": findings,
        "hypotheses": hypotheses,
        "earliest_observed_failure": failure.get("earliest_observed_failure"),
        "unknowns": list(dict.fromkeys(unknowns)),
        "next_steps": list(dict.fromkeys(next_steps)),
        "warnings": list(dict.fromkeys(state["warnings"])),
        "notes": list(dict.fromkeys(state["notes"])),
        "queries": state["queries"],
        "artifacts": state["artifacts"],
        "coverage": {
            "observed_events": len(state["events"]),
            "complete": not bool(state["warnings"]),
            "note": "完整仅指本次检索与分析未报告截断，不保证系统已记录所有调用",
        },
    }
    report["markdown"] = render_markdown(report)
    return report
