"""Budget-aware evidence packing, independent of the model and workflow runtime."""

import json

from troubleshooter.analysis import time_key
from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.logs.cleaning import model_evidence

from .budget import RunBudget, estimate_tokens
from .state import InvestigationState


def _fragment_text(text: str, maximum_bytes: int) -> list[str]:
    parts = []
    current = ""
    current_size = 0
    for char in text:
        char_size = len(char.encode())
        if current and current_size + char_size > maximum_bytes:
            parts.append(current)
            current = ""
            current_size = 0
        current += char
        current_size += char_size
    if current:
        parts.append(current)
    return parts


def _fragment_item(item: dict, serialized: str, chunk_budget: int) -> list[list[dict]]:
    event_id = item.get("id", item.get("event_id"))
    parts = _fragment_text(serialized, chunk_budget // 2)
    return [
        [
            {
                "event_id": event_id,
                "fragment": part,
                "part": index + 1,
                "total_parts": len(parts),
            }
        ]
        for index, part in enumerate(parts)
    ]


def _pack_items(data: list[dict], chunk_budget: int) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_size = 0
    for item in data:
        serialized = json.dumps(item, ensure_ascii=False)
        item_size = estimate_tokens(serialized)
        if item_size > chunk_budget:
            if current:
                chunks.append(current)
                current = []
                current_size = 0
            chunks.extend(_fragment_item(item, serialized, chunk_budget))
            continue
        if current and current_size + item_size > chunk_budget:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += item_size
    if current:
        chunks.append(current)
    return chunks


def _prioritize_failures(chunks: list[list[dict]], state: InvestigationState) -> None:
    failed_ids = {
        failure["event_id"]
        for failure in state["artifacts"]
        .get("failure-localization", {})
        .get("failures", [])
    }
    chunks.sort(
        key=lambda chunk: (
            not any(
                item.get("id", item.get("event_id")) in failed_ids for item in chunk
            )
        )
    )


def prepare_chunks(
    state: InvestigationState,
    request: InvestigationRequest,
    config: dict,
    budget: RunBudget,
) -> list[list[dict]]:
    events = sorted(state["events"].values(), key=time_key)
    data = model_evidence(
        events, state["records"], request.cleaning_enabled, config["cleaning"]
    )
    budget.usage.before_chars = len(
        json.dumps(list(state["records"].values()), ensure_ascii=False)
    )
    budget.usage.after_chars = len(json.dumps(data, ensure_ascii=False))
    # 为提示词、问题和一次格式修复预留空间，避免分块刚好塞满输入预算。
    chunk_budget = max(500, budget.input_limit - 6000)
    chunks = _pack_items(data, chunk_budget)
    _prioritize_failures(chunks, state)
    return chunks
