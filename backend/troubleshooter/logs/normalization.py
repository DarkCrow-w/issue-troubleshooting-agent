"""Normalize heterogeneous Splunk records without discarding source evidence."""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from troubleshooter.domain.models import Event

EXCEPTION_CLASS = re.compile(r"\b[A-Z][A-Za-z0-9_$]{0,100}(?:Exception|Error)\b")
HTTP_STATUS = re.compile(r"^\s*(\d{3})(?:\s|$)")
MAX_EXCEPTION_MESSAGE_CHARS = 4_000


def compact_exception_message(message: str) -> str:
    """限制派生异常摘要的长度；完整异常仍保存在原始日志和 stack 字段中。"""

    if len(message) <= MAX_EXCEPTION_MESSAGE_CHARS:
        return message

    tail_chars = 1_000
    head_chars = MAX_EXCEPTION_MESSAGE_CHARS - tail_chars
    omitted_chars = len(message) - MAX_EXCEPTION_MESSAGE_CHARS
    omission = f" ... 省略 {omitted_chars} 字符 ... "
    return message[:head_chars] + omission + message[-tail_chars:]


def decode_payload(value: Any, warnings: list[str]) -> Any:
    """最多解开三层字符串化 JSON；解析失败保留原文，不丢弃排查证据。"""
    if not isinstance(value, str):
        return value
    decoded = value
    for _ in range(3):
        if not isinstance(decoded, str) or not decoded.lstrip().startswith(("{", "[", '"')):
            break
        try:
            decoded = json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            warnings.append("请求/响应含非 JSON 文本，已保留原文")
            break
    return decoded


def walk_fields(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk_fields(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_fields(item)


def normalize_time(value: Any) -> str:
    try:
        if isinstance(value, (int, float)) or re.fullmatch(r"\d+(\.\d+)?", str(value)):
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except (ValueError, OverflowError, OSError):
        return str(value or "")


def parse_http_status(value: Any, warnings: list[str]) -> int | None:
    """兼容 Splunk 中的整数状态码和 ``503 Service Unavailable`` 形式。"""

    if value is None:
        return None
    if isinstance(value, bool):
        warnings.append("HTTP 状态无法解析")
        return None
    if isinstance(value, int) and 100 <= value <= 599:
        return value
    match = HTTP_STATUS.match(str(value))
    if match:
        status = int(match.group(1))
        if 100 <= status <= 599:
            return status
    warnings.append("HTTP 状态无法解析")
    return None


def extract_exceptions(text: str) -> list[tuple[str, str]]:
    """线性查找 Java 异常；再向左补包名，避免在数 MB 文本上反复回溯。"""

    output = []
    for match in EXCEPTION_CLASS.finditer(text):
        start = match.start()
        cursor = start
        segments = 0
        while cursor > 1 and text[cursor - 1] == "." and segments < 12:
            token_end = cursor - 1
            token_start = token_end
            while token_start > 0 and token_end - token_start < 101:
                previous = text[token_start - 1]
                if not (previous.isalnum() or previous in "_$"):
                    break
                token_start -= 1
            if token_start == token_end:
                break
            start = token_start
            cursor = token_start
            segments += 1

        message = ""
        message_start = match.end()
        if text[message_start : message_start + 1] == ":":
            message_start += 1
            message_end = text.find("\n", message_start)
            if message_end < 0:
                message_end = len(text)
            message = text[message_start:message_end].strip()
            message = compact_exception_message(message)
        output.append((text[start : match.end()], message))
    return output


def normalize(record: dict, config: dict) -> Event:
    raw = record.get("_raw", "")
    warnings: list[str] = []
    fields = dict(record)
    # _raw 可补全 Splunk 未提取的字段；冲突时优先提取字段，同时留下告警。
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            raw_fields = json.loads(raw)
            if isinstance(raw_fields, dict):
                conflicts = [k for k in raw_fields if k in fields and fields[k] != raw_fields[k]]
                if conflicts:
                    warnings.append("提取字段与 _raw 冲突，优先提取字段：" + ", ".join(conflicts))
                fields = {**raw_fields, **fields}
        except json.JSONDecodeError:
            warnings.append("_raw JSON 无法解析，已保留原文")
    service = str(fields.get("appName") or fields.get("app") or fields.get("service") or "unknown")
    service = config.get("service_aliases", {}).get(service, service)
    request = next(
        (
            fields[k]
            for k in ("reqMessage", "request", "serviceData", "CM_PARAM")
            if fields.get(k) is not None
        ),
        None,
    )
    response = next(
        (
            fields[k]
            for k in ("response", "respMessage", "responseBody")
            if fields.get(k) is not None
        ),
        None,
    )
    request = decode_payload(request, warnings)
    response = decode_payload(response, warnings)
    ids = {}
    id_fields = set(config["correlation_fields"]) | {
        "contextId",
        "x_request_id",
        "sequenceNumber",
        "traceparent",
        "spanId",
        "parentSpanId",
    }
    for key, value in (
        list(walk_fields(request)) + list(walk_fields(response)) + list(fields.items())
    ):
        if key in id_fields and isinstance(value, (str, int)) and str(value) not in ("", "<null>"):
            ids[key] = str(value)
    for key in id_fields:
        if key not in ids and isinstance(raw, str):
            match = re.search(rf'\b{re.escape(key)}\s*[=:]\s*["\']?([\w.:/-]+)', raw)
            if match:
                ids[key] = match.group(1)
    correlation_ids = {ids[k] for k in config["correlation_fields"] if k in ids}
    if service in config.get("composite_id_services", []) and ":" in ids.get("seqNo", ""):
        root, business_id = ids["seqNo"].split(":", 1)
        correlation_ids.add(root)
        ids["businessSequence"] = business_id
    message = str(fields.get("message") or raw)
    # Java 日志框架对异常字段命名不统一。按信息完整度选择第一个非空来源，
    # message/throwable 是结构化日志里很常见的两种形式。
    exception_text = str(
        fields.get("stacktrace")
        or fields.get("throwable")
        or fields.get("exception")
        or fields.get("message")
        or raw
    )
    matches = extract_exceptions(exception_text)
    exception = None
    if matches:
        exception = {
            "type": matches[0][0],
            "message": matches[0][1],
            "causes": [{"type": kind, "message": message} for kind, message in matches[1:]],
            "stack": exception_text,
        }
    kind = str(fields.get("eventType", "")).lower()
    if kind not in ("request", "response", "exception"):
        if exception:
            kind = "exception"
        elif response is not None or re.search(r"\bresponse\b", message, re.I):
            kind = "response"
        elif request is not None or re.search(r"\brequest\b", message, re.I):
            kind = "request"
        else:
            kind = "log"
    status = parse_http_status(
        fields.get("httpStatus", fields.get("statusCode", fields.get("status"))), warnings
    )
    business_code = fields.get("businessCode", fields.get("errorCode"))
    if business_code is None:
        business_code = next(
            (v for k, v in walk_fields(response) if k in ("code", "returnCode", "errorCode")), None
        )
    timestamp = normalize_time(fields.get("_time", fields.get("timestamp")))
    if not timestamp:
        warnings.append("事件缺少时间")
    if record.get("_cd"):
        identity = {
            key: record.get(key) for key in ("index", "_bkt", "_cd", "source", "_time", "_raw")
        }
    else:
        identity = {key: value for key, value in record.items() if key not in ("_serial", "_si")}
    stable_content = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
    event_id = "ev_" + hashlib.sha256(stable_content.encode()).hexdigest()[:16]
    return Event(
        id=event_id,
        timestamp=timestamp,
        service=service,
        instance=str(fields.get("pod") or fields.get("host") or ""),
        ids=ids,
        correlation_ids=sorted(correlation_ids),
        api=str(
            fields.get("serviceId")
            or fields.get("path")
            or fields.get("x_envoy_original_path")
            or ""
        ),
        method=str(fields.get("IN_METHOD") or fields.get("method") or ""),
        direction=str(fields.get("direction", "unknown")).lower(),
        kind=kind,
        level=str(fields.get("level", "")).upper(),
        message=message,
        request=request,
        response=response,
        http_status=status,
        business_code=str(business_code) if business_code is not None else None,
        exception=exception,
        peer_service=str(fields.get("peerService", "")),
        call_id=str(fields.get("callId") or fields.get("spanId") or ""),
        parent_call_id=str(fields.get("parentCallId") or fields.get("parentSpanId") or ""),
        attempt=str(fields.get("attempt") or fields.get("x_envoy_attempt_count") or ""),
        source={
            k: fields[k] for k in ("index", "source", "sourcetype", "_cd", "_bkt") if k in fields
        },
        parse_warnings=warnings,
    )
