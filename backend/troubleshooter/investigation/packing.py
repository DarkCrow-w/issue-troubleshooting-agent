"""Budget-aware evidence packing, independent of the model and workflow runtime."""

import json

from troubleshooter.analysis import time_key
from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.logs.cleaning import model_evidence

from .budget import RunBudget, estimate_tokens
from .state import InvestigationState


def prepare_chunks(
    state: InvestigationState, request: InvestigationRequest, config: dict, budget: RunBudget
) -> list[list[dict]]:
    events = sorted(state["events"].values(), key=time_key)
    data = model_evidence(events, state["records"], request.cleaning_enabled, config["cleaning"])
    budget.usage.before_chars = len(json.dumps(list(state["records"].values()), ensure_ascii=False))
    budget.usage.after_chars = len(json.dumps(data, ensure_ascii=False))
    # 为提示词、问题和一次格式修复预留空间，避免分块刚好塞满输入预算。
    chunk_budget = max(500, budget.input_limit - 6000)
    chunks, current, size = [], [], 0
    for item in data:
        serialized = json.dumps(item, ensure_ascii=False)
        item_size = estimate_tokens(serialized)
        if item_size > chunk_budget:
            if current:
                chunks.append(current)
                current, size = [], 0
            event_id = item.get("id", item.get("event_id"))
            # 超长记录按 UTF-8 字节预算分片，所有片段保留同一证据 ID，不静默截断。
            piece = ""
            piece_size = 0
            parts = []
            for char in serialized:
                char_size = len(char.encode())
                if piece_size + char_size > chunk_budget // 2:
                    parts.append(piece)
                    piece, piece_size = "", 0
                piece += char
                piece_size += char_size
            if piece:
                parts.append(piece)
            for i, part in enumerate(parts):
                chunks.append(
                    [
                        {
                            "event_id": event_id,
                            "fragment": part,
                            "part": i + 1,
                            "total_parts": len(parts),
                        }
                    ]
                )
            continue
        if current and size + item_size > chunk_budget:
            chunks.append(current)
            current, size = [], 0
        current.append(item)
        size += item_size
    if current:
        chunks.append(current)
    # 预算不足以分析全部材料时，优先处理包含失败信号的分块。
    failed = {
        f["event_id"]
        for f in state["artifacts"].get("failure-localization", {}).get("failures", [])
    }
    chunks.sort(
        key=lambda chunk: not any(item.get("id", item.get("event_id")) in failed for item in chunk)
    )
    return chunks
