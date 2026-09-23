"""为模型构建紧凑证据；PostgreSQL 中的原始记录不受这里影响。"""

import json
import re
from typing import Any

from troubleshooter.domain.models import Event

from .normalization import walk_fields

ERROR_SIGNAL = re.compile(
    r"""(?ix)
    caused\s+by
    | \b[A-Z][A-Za-z0-9_$]{0,100}(?:Exception|Error)\b
    | \b(?:error|fatal|failed|failure|rejected)\b
    | time(?:d)?\s*out
    | deadlock
    | connection\s+(?:refused|reset)
    | sqlstate
    | \bhttp\s*[45]\d{2}\b
    | \\?["']?(?:errorCode|returnCode|businessCode|statusCode)\\?["']?\s*[:=]
    """
)


def _sample_positions(positions: list[int], limit: int) -> list[int]:
    """错误很多时均匀取样，不能只保留日志开头的信号。"""

    if len(positions) <= limit:
        return positions
    if limit <= 1:
        return [positions[-1]]
    indexes = {
        round(index * (len(positions) - 1) / (limit - 1)) for index in range(limit)
    }
    return [positions[index] for index in sorted(indexes)]


def _merge_ranges(ranges: list[tuple[int, int]], total: int) -> list[tuple[int, int]]:
    normalized = sorted(
        (max(0, start), min(total, end)) for start, end in ranges if start < end
    )
    merged: list[list[int]] = []
    for start, end in normalized:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _text_excerpts(text: str, config: dict) -> list[dict[str, Any]]:
    """保留头尾及错误附近窗口，返回位置以便模型理解中间存在省略。"""

    total = len(text)
    maximum = config["body_max_chars"]
    if total <= maximum:
        return [{"kind": "complete", "start": 0, "end": total, "text": text}]

    head = min(config["head_chars"], maximum)
    tail = min(config["tail_chars"], maximum - head)
    window = config["signal_window_chars"]
    positions = [match.start() for match in ERROR_SIGNAL.finditer(text)]
    positions = _sample_positions(positions, config["max_signal_windows"])

    ranges = [(0, head), (total - tail, total)]
    for position in positions:
        before = window // 2
        ranges.append((position - before, position + window - before))
    ranges = _merge_ranges(ranges, total)

    # 配置的最坏组合也应受 body_max_chars 约束；后面的窗口优先保留尾部错误。
    remaining = maximum
    bounded: list[tuple[int, int]] = []
    for start, end in reversed(ranges):
        length = min(end - start, remaining)
        if length <= 0:
            break
        bounded.append((end - length, end))
        remaining -= length
    bounded.reverse()

    excerpts = []
    for start, end in bounded:
        kinds = []
        if start == 0:
            kinds.append("head")
        if end == total:
            kinds.append("tail")
        if any(start <= position < end for position in positions):
            kinds.append("error_signal")
        excerpts.append(
            {
                "kind": "+".join(kinds) or "context",
                "start": start,
                "end": end,
                "text": text[start:end],
            }
        )
    return excerpts


def _compact_value(value: Any, config: dict) -> Any:
    """关键字段也要限长，否则一个 systemHeader 就可能挤掉其他证据。"""

    rendered = json.dumps(value, ensure_ascii=False, default=str)
    limit = config["selected_field_max_chars"]
    if len(rendered) <= limit:
        return value
    half = limit // 2
    return {
        "preview": rendered[:half] + rendered[-half:],
        "original_chars": len(rendered),
        "truncated": True,
    }


def _compact_body(body: Any, event_id: str, config: dict) -> Any:
    rendered = json.dumps(body, ensure_ascii=False, default=str)
    if len(rendered) <= config["body_max_chars"]:
        return body
    selected = {
        key: _compact_value(value, config)
        for key, value in walk_fields(body)
        if key in config["keep_body_fields"]
    }
    excerpts = _text_excerpts(rendered, config)
    return {
        "selected_fields": selected,
        "excerpts": excerpts,
        "original_chars": len(rendered),
        "retained_chars": sum(len(item["text"]) for item in excerpts),
        "truncated": True,
        "evidence_id": event_id,
    }


def _compact_stack(stack: str, config: dict) -> tuple[str, bool]:
    lines = stack.splitlines()
    maximum = config["stack_max_frames"]
    truncated = len(lines) > maximum
    compacted = stack
    if truncated:
        # 首尾负责上下文；Caused by 和异常标题附近负责保留真正的异常链。
        keep = set(range(min(20, maximum, len(lines))))
        tail_count = min(10, max(0, maximum - len(keep)))
        keep.update(range(max(0, len(lines) - tail_count), len(lines)))
        for index, line in enumerate(lines):
            if not ERROR_SIGNAL.search(line):
                continue
            for nearby in range(max(0, index - 1), min(len(lines), index + 6)):
                if len(keep) >= maximum:
                    break
                keep.add(nearby)
            if len(keep) >= maximum:
                break

        output = []
        previous = -1
        for index in sorted(keep):
            if previous >= 0 and index > previous + 1:
                output.append(f"... 省略 {index - previous - 1} 行 ...")
            output.append(lines[index])
            previous = index
        compacted = "\n".join(output)

    # 有些 logger 把完整异常写成单行；行数限制对这种数 MB 文本不起作用。
    if len(compacted) > config["body_max_chars"]:
        excerpts = _text_excerpts(compacted, config)
        compacted = "\n".join(
            f"[字符 {item['start']}..{item['end']} · {item['kind']}]\n{item['text']}"
            for item in excerpts
        )
        truncated = True
    return compacted, truncated


def clean_event(event: Event, config: dict) -> dict:
    result = event.model_dump(exclude_none=True)
    for key in ("request", "response"):
        if result.get(key) is not None:
            result[key] = _compact_body(result[key], event.id, config)
    if event.exception:
        stack, truncated = _compact_stack(event.exception["stack"], config)
        result["exception"]["stack"] = stack
        result["exception"]["stack_truncated"] = truncated
    message = result["message"]
    if event.exception and message == event.exception["stack"]:
        result["message"] = {"same_content_as": "exception.stack"}
    elif len(message) > config["body_max_chars"]:
        excerpts = _text_excerpts(message, config)
        result["message"] = {
            "excerpts": excerpts,
            "original_chars": len(message),
            "retained_chars": sum(len(item["text"]) for item in excerpts),
        }
        result["message_truncated"] = True
    return {k: v for k, v in result.items() if v not in ("", [], {}, None)}


def model_evidence(
    events: list[Event], records: dict[str, dict], cleaning: bool, config: dict
) -> list[dict]:
    if not cleaning:
        return [
            {"event_id": e.id, "normalized": e.model_dump(), "record": records[e.id]}
            for e in events
        ]
    # Splunk 来源位置只用于证据回查，对模型判断交易问题没有帮助。原始值仍完整保存在
    # PostgreSQL，不会因为模型输入清洗而丢失。
    #
    # 同一交易的大部分日志会重复携带整组 trace IDs。只保留第一份并建立证据引用，
    # 每个事件自己的时间、服务、类型和消息仍独立保留。
    payloads: dict[tuple[str, str], str] = {}
    output = []
    for event in events:
        item = clean_event(event, config)
        item.pop("source", None)
        for key in ("ids", "request", "response", "exception"):
            if key not in item:
                continue
            fingerprint = (
                key,
                json.dumps(item[key], sort_keys=True, ensure_ascii=False),
            )
            if fingerprint in payloads:
                item[key] = {"same_content_as": payloads[fingerprint], "field": key}
            else:
                payloads[fingerprint] = event.id
        output.append(item)
    return output
