"""生成与页面相同证据来源的 Markdown 报告。"""

STATUS_LABELS = {
    "success": "正常",
    "failed": "发现错误",
    "affected": "受错误影响",
    "warning": "证据不完整",
    "unknown": "待确认",
}

PHASE_LABELS = {
    "request": "请求发送",
    "request_processing": "请求处理",
    "response": "响应返回",
    "response_processing": "响应后处理",
    "unknown": "待确认",
}


def table_cell(value) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def _table_row(values) -> str:
    return "| " + " | ".join(table_cell(value) for value in values) + " |"


def _journey_lines(journey: dict) -> list[str]:
    attribution = journey.get("attribution", {})
    conclusion = attribution.get("conclusion", {})
    lines = [
        "# 交易排查报告",
        "",
        "## 明确结论",
        "",
        f"**{conclusion.get('title', attribution.get('label', '故障位置待确认'))}**",
        "",
        conclusion.get("detail", attribution.get("summary", "尚未生成链路定位结果。")),
        "",
        f"处理建议：{conclusion.get('action', '请结合完整日志继续排查。')}",
        "",
        "## 交易链路定位",
        "",
        f"**故障区域：{attribution.get('label', '待确认')}**",
        "",
        attribution.get("summary", "尚未生成链路定位结果。"),
        "",
        attribution.get("caution", ""),
        "",
        "| 区域 | 状态 | 服务 / API | 失败阶段 | Request 证据 | Response 证据 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for stage in journey.get("stages", []):
        if not stage.get("nodes"):
            lines.append(
                _table_row(
                    (
                        stage["label"],
                        STATUS_LABELS.get(stage["status"], stage["status"]),
                        "未观测到",
                        "—",
                        "—",
                        "—",
                    )
                )
            )
            continue
        for node in stage["nodes"]:
            service_api = f"{node['service']} · {node.get('api') or 'API 未知'}"
            lines.append(
                _table_row(
                    (
                        stage["label"],
                        STATUS_LABELS.get(node["status"], node["status"]),
                        service_api,
                        PHASE_LABELS.get(node.get("failure_phase", ""), "—"),
                        ", ".join(node.get("request_ids", [])),
                        ", ".join(node.get("response_ids", [])),
                    )
                )
            )
    return lines


def _graph_lines(report: dict) -> list[str]:
    graph = report["graph"]
    lines = [
        "",
        "## 详细分析",
        "",
        report["summary"],
        "",
        "## 服务与 API",
        "",
        "| 调用实例 | 服务 | API | 证据 |",
        "| --- | --- | --- | --- |",
    ]
    for node in graph["nodes"]:
        lines.append(
            _table_row(
                (
                    node["id"],
                    node["service"],
                    node["api"],
                    ", ".join(node["evidence_ids"]),
                )
            )
        )
    lines.extend(["", "## 调用关系", ""])
    if not graph["edges"]:
        lines.append("缺少足够证据建立调用边；节点顺序不代表调用关系。")
    for edge in graph["edges"]:
        certainty = "明确" if edge["certainty"] == "confirmed" else "推测"
        lines.append(
            f"- {edge['source']} → {edge['target']}（{certainty}）：{edge['reason']}"
            f"；证据：{', '.join(edge['evidence_ids'])}"
        )
    return lines


def _failure_lines(report: dict) -> list[str]:
    first = report.get("earliest_observed_failure")
    if not first:
        return []
    return [
        "",
        "## 最早观测到的失败",
        "",
        f"{first['timestamp']} · {first['service']} · {first['event_id']}",
        "",
        "最早观测到的失败不等同于根因，跨主机时钟可能存在偏差。",
    ]


def _claim_lines(report: dict) -> list[str]:
    lines = ["", "## 观测事实", ""]
    lines.extend(
        f"- {finding['statement']}（证据：{', '.join(finding['evidence_ids'])}）"
        for finding in report["findings"]
    )
    sections = (
        ("根因假设", "hypotheses"),
        ("未知信息", "unknowns"),
        ("下一步", "next_steps"),
        ("限制与告警", "warnings"),
        ("运行说明", "notes"),
    )
    for title, key in sections:
        lines.extend(["", "## " + title, ""])
        for item in report[key]:
            if not isinstance(item, dict):
                lines.append("- " + item)
                continue
            lines.append(
                f"- {item['statement']}（{item['confidence']}；"
                f"证据：{', '.join(item['evidence_ids'])}）"
            )
            if item.get("counter_evidence_ids"):
                lines.append("  反对证据：" + ", ".join(item["counter_evidence_ids"]))
            if item.get("verification"):
                lines.append("  验证方式：" + item["verification"])
    return lines


def _timeline_lines(report: dict) -> list[str]:
    lines = [
        "",
        "## 日志时间线",
        "",
        "| 时间 | 服务 | 类型 | 证据 |",
        "| --- | --- | --- | --- |",
    ]
    for event in report["graph"]["timeline"]:
        lines.append(
            _table_row(
                event[key] for key in ("timestamp", "service", "kind", "event_id")
            )
        )
    return lines


def _query_lines(report: dict) -> list[str]:
    lines = ["", "## 查询记录", ""]
    for query in report["queries"]:
        start_time = query["start_time"] or "未指定"
        end_time = query["end_time"] or "未指定"
        lines.append(
            f"- {query['reason']}：{query['count']} 条结果；"
            f"时间范围 {start_time} 至 {end_time}。"
        )
    return lines


def render_markdown(report: dict) -> str:
    sections = (
        _journey_lines(report.get("journey", {})),
        _graph_lines(report),
        _failure_lines(report),
        _claim_lines(report),
        _timeline_lines(report),
        _query_lines(report),
    )
    return "\n".join(line for section in sections for line in section)
