"""Bounded context shared between composed skills."""

import json


def compact_artifacts(artifacts: dict) -> dict:
    """Share preceding skills with explicit bounds; source evidence is sent in chunks."""
    result = {}
    for key, value in artifacts.items():
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
