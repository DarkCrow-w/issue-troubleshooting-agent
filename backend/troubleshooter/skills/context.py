"""Bounded context shared between composed skills."""

import json


def _journey_summary(value: dict) -> dict:
    """让模型看到确定性归因，不重复传整份前端展示结构。"""
    stages = []
    for stage in value.get("stages", []):
        problem_nodes = [
            {
                "service": node.get("service"),
                "api": node.get("api"),
                "status": node.get("status"),
                "failure_phase": node.get("failure_phase"),
                "phases": node.get("phases", {}),
                "evidence_ids": node.get("evidence_ids", []),
            }
            for node in stage.get("nodes", [])
            if node.get("status") in ("failed", "warning")
        ]
        stages.append(
            {
                "id": stage.get("id"),
                "status": stage.get("status"),
                "node_count": len(stage.get("nodes", [])),
                "problem_nodes": problem_nodes[:2],
            }
        )
    return {"attribution": value.get("attribution", {}), "stages": stages}


def compact_artifacts(artifacts: dict) -> dict:
    """Share preceding skills with explicit bounds; source evidence is sent in chunks."""
    result = {}
    for key, value in artifacts.items():
        if key == "transaction-journey":
            result[key] = _journey_summary(value)
            continue
        text = json.dumps(value, ensure_ascii=False)
        if len(text.encode()) <= 1200:
            result[key] = value
        else:
            result[key] = {
                "preview": text[:300],
                "truncated": True,
                "note": "完整结果保留在报告 artifacts 中",
            }
    return result
