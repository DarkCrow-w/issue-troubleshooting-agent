"""Build the report from collected facts; usable after success, failure or cancellation."""

from troubleshooter.investigation.state import InvestigationState

from .markdown import render_markdown


def build_report(state: InvestigationState) -> dict:
    failure = state["artifacts"].get("failure-localization", {})
    failures = failure.get("failures", [])
    graph = state["artifacts"].get(
        "trace-reconstruction", {"nodes": [], "edges": [], "timeline": [], "services": []}
    )
    findings, hypotheses, unknowns, next_steps = [], [], [], []
    for diagnosis in state["diagnoses"]:
        findings.extend(c.model_dump() for c in diagnosis.findings)
        hypotheses.extend(c.model_dump() for c in diagnosis.hypotheses)
        unknowns.extend(diagnosis.unknowns)
        next_steps.extend(diagnosis.next_steps)
    if not state["diagnoses"]:
        findings = [
            {
                "statement": f"{f['service']}：" + "；".join(f["reasons"]),
                "evidence_ids": [f["event_id"]],
                "confidence": "high",
            }
            for f in failures
        ]
        if failures:
            unknowns.append("现有规则只能确认失败信号，无法确认最终根因与异常传播关系")
            next_steps.append("检查失败事件的完整异常链和下游响应，验证根因假设")
    for node in graph["nodes"]:
        if node.get("missing_response"):
            unknowns.append(f"{node['service']} {node['api']} 未找到可配对响应（{node['id']}）")
    if len(graph["services"]) > 1 and not graph["edges"]:
        unknowns.append("日志覆盖多个服务，但缺少足够证据建立调用关系")
    summaries = [d.summary for d in state["diagnoses"]]
    summary = (
        "\n".join(summaries)
        if summaries
        else (
            f"在 {len(graph['services'])} 个服务中发现 {len(failures)} 个失败信号；根因尚未确认。"
            if failures
            else "未发现明确失败信号；这不证明交易已成功。"
        )
    )
    report = {
        "summary": summary,
        "graph": graph,
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
