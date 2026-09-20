"""Human-readable export of the same evidence-backed report shown in the UI."""


def table_cell(value) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict) -> str:
    lines = [
        "# 交易排查报告",
        "",
        report["summary"],
        "",
        "## 服务与 API",
        "",
        "| 调用实例 | 服务 | API | 证据 |",
        "| --- | --- | --- | --- |",
    ]
    for node in report["graph"]["nodes"]:
        cells = (node["id"], node["service"], node["api"], ", ".join(node["evidence_ids"]))
        lines.append("| " + " | ".join(table_cell(cell) for cell in cells) + " |")
    lines.extend(["", "## 调用关系", ""])
    if not report["graph"]["edges"]:
        lines.append("缺少足够证据建立调用边；节点顺序不代表调用关系。")
    for edge in report["graph"]["edges"]:
        certainty = "明确" if edge["certainty"] == "confirmed" else "推测"
        lines.append(
            f"- {edge['source']} → {edge['target']}（{certainty}）：{edge['reason']}"
            f"；证据：{', '.join(edge['evidence_ids'])}"
        )
    first = report.get("earliest_observed_failure")
    if first:
        lines.extend(
            [
                "",
                "## 最早观测到的失败",
                "",
                f"{first['timestamp']} · {first['service']} · {first['event_id']}",
                "",
                "最早观测到的失败不等同于根因，跨主机时钟可能存在偏差。",
            ]
        )
    lines.extend(["", "## 观测事实", ""])
    lines.extend(
        f"- {f['statement']}（证据：{', '.join(f['evidence_ids'])}）" for f in report["findings"]
    )
    for title, key in (
        ("根因假设", "hypotheses"),
        ("未知信息", "unknowns"),
        ("下一步", "next_steps"),
        ("限制与告警", "warnings"),
        ("运行说明", "notes"),
    ):
        lines.extend(["", "## " + title, ""])
        for item in report[key]:
            if isinstance(item, dict):
                lines.append(
                    f"- {item['statement']}（{item['confidence']}；证据：{', '.join(item['evidence_ids'])}）"
                )
                if item.get("counter_evidence_ids"):
                    lines.append("  反对证据：" + ", ".join(item["counter_evidence_ids"]))
                if item.get("verification"):
                    lines.append("  验证方式：" + item["verification"])
            else:
                lines.append("- " + item)
    lines.extend(
        ["", "## 日志时间线", "", "| 时间 | 服务 | 类型 | 证据 |", "| --- | --- | --- | --- |"]
    )
    for event in report["graph"]["timeline"]:
        lines.append(
            "| "
            + " | ".join(
                table_cell(event[key]) for key in ("timestamp", "service", "kind", "event_id")
            )
            + " |"
        )
    lines.extend(["", "## 查询记录", ""])
    for query in report["queries"]:
        lines.append(
            f"- {query['reason']}：{query['count']} 条结果；"
            f"时间范围 {query['start_time']} 至 {query['end_time']}。"
        )
    return "\n".join(lines)
