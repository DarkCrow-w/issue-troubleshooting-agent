"""Normalize heterogeneous Splunk records without discarding source evidence."""

import hashlib
import json
import re
from datetime import datetime, timezone
from itertools import chain
from typing import Any

from troubleshooter.domain.models import Event

from .java_log import parse_java_log

EXCEPTION_CLASS = re.compile(r"\b[A-Z][A-Za-z0-9_$]{0,100}(?:Exception|Error)\b")
HTTP_STATUS = re.compile(r"^\s*(\d{3})(?:\s|$)")
REQUEST_MESSAGE = re.compile(
    r"\b(?:send|receive|received|handle|execute)?\s*(?:request|req)\s+"
    r"(?:is|body|message|received|sent)\b",
    re.IGNORECASE,
)
RESPONSE_MESSAGE = re.compile(
    r"\b(?:send|receive|received|handle|execute)?\s*(?:response|res)\s+"
    r"(?:is|body|message|received|sent)\b",
    re.IGNORECASE,
)
MAX_EXCEPTION_MESSAGE_CHARS = 4_000
REQUEST_FIELDS = ("reqMessage", "request", "serviceData", "CM_PARAM")
RESPONSE_FIELDS = ("response", "respMessage", "responseBody")
DEFAULT_ID_FIELDS = {
    "contextId",
    "x_request_id",
    "sequenceNumber",
    "traceparent",
    "spanId",
    "parentSpanId",
}


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
        if not isinstance(decoded, str) or not decoded.lstrip().startswith(
            ("{", "[", '"')
        ):
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


def _first_value(fields: dict, names: tuple[str, ...]) -> Any:
    return next((fields[name] for name in names if fields.get(name) is not None), None)


def _merge_raw_fields(record: dict, warnings: list[str]) -> tuple[dict, Any]:
    """结构化字段优先于 ``_raw`` JSON，同时显式记录冲突。"""

    raw = record.get("_raw", "")
    fields = dict(record)
    if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
        return fields, raw
    try:
        raw_fields = json.loads(raw)
    except json.JSONDecodeError:
        warnings.append("_raw JSON 无法解析，已保留原文")
        return fields, raw
    if not isinstance(raw_fields, dict):
        return fields, raw
    conflicts = [
        key for key in raw_fields if key in fields and fields[key] != raw_fields[key]
    ]
    if conflicts:
        warnings.append("提取字段与 _raw 冲突，优先提取字段：" + ", ".join(conflicts))
    return {**raw_fields, **fields}, raw


def _payloads(fields: dict, java_log, warnings: list[str]) -> tuple[Any, Any]:
    request = _first_value(fields, REQUEST_FIELDS)
    response = _first_value(fields, RESPONSE_FIELDS)
    request = java_log.request if request is None else request
    response = java_log.response if response is None else response
    return decode_payload(request, warnings), decode_payload(response, warnings)


def _id_from_raw(raw: Any, key: str) -> str:
    if not isinstance(raw, str):
        return ""
    # 空字段后常紧跟下一个 ``key=value``，不能把下一个 key 当作当前 ID。
    match = re.search(
        rf"\b{re.escape(key)}[ \t]*[=:][ \t]*[\"']?"
        rf"(?:\[(?P<bracket>[\w.:/-]+)]|"
        rf"(?![A-Za-z][\w.-]*[=:])(?P<plain>[\w.:/-]+))",
        raw,
    )
    if not match:
        return ""
    return match.group("bracket") or match.group("plain")


def _identifiers(
    fields: dict,
    request: Any,
    response: Any,
    raw: Any,
    java_log,
    config: dict,
) -> dict[str, str]:
    ids = dict(java_log.identifiers)
    id_fields = set(config["correlation_fields"]) | DEFAULT_ID_FIELDS
    values = chain(walk_fields(request), walk_fields(response), fields.items())
    for key, value in values:
        if (
            key in id_fields
            and isinstance(value, (str, int))
            and str(value) not in ("", "<null>")
        ):
            ids[key] = str(value)
    for key in id_fields:
        if key not in ids and (value := _id_from_raw(raw, key)):
            ids[key] = value
    return ids


def _correlation_ids(ids: dict[str, str], service: str, config: dict) -> list[str]:
    values = {ids[key] for key in config["correlation_fields"] if key in ids}
    if service in config.get("composite_id_services", []) and ":" in ids.get(
        "seqNo", ""
    ):
        root, business_id = ids["seqNo"].split(":", 1)
        values.add(root)
        ids["businessSequence"] = business_id
    return sorted(values)


def _exception(fields: dict, raw: Any) -> dict | None:
    # Java 日志框架对异常字段命名不统一。按信息完整度选择第一个非空来源，
    # message/throwable 是结构化日志里很常见的两种形式。
    exception_text = str(
        fields.get("stacktrace")
        or fields.get("throwable")
        or fields.get("exception")
        or raw
        or fields.get("message")
    )
    matches = extract_exceptions(exception_text)
    if not matches:
        return None
    first_type, first_message = matches[0]
    return {
        "type": first_type,
        "message": first_message,
        "causes": [{"type": kind, "message": message} for kind, message in matches[1:]],
        "stack": exception_text,
    }


def _event_kind(
    fields: dict,
    java_log,
    exception: dict | None,
    request: Any,
    response: Any,
    message: str,
) -> str:
    kind = str(fields.get("eventType", "")).lower()
    if kind in ("request", "response", "exception"):
        return kind
    if exception:
        return "exception"
    if java_log.kind:
        return java_log.kind
    if response is not None or RESPONSE_MESSAGE.search(message):
        return "response"
    if request is not None or REQUEST_MESSAGE.search(message):
        return "request"
    return "log"


def _business_code(fields: dict, response: Any) -> Any:
    direct = _first_value(fields, ("businessCode", "errorCode"))
    if direct is not None:
        return direct
    return next(
        (
            value
            for key, value in walk_fields(response)
            if key in ("code", "returnCode", "errorCode")
        ),
        None,
    )


def _event_id(record: dict) -> str:
    if record.get("_cd"):
        identity = {
            key: record.get(key)
            for key in ("index", "_bkt", "_cd", "source", "_time", "_raw")
        }
    else:
        identity = {
            key: value for key, value in record.items() if key not in ("_serial", "_si")
        }
    stable_content = json.dumps(
        identity, sort_keys=True, ensure_ascii=False, default=str
    )
    return "ev_" + hashlib.sha256(stable_content.encode()).hexdigest()[:16]


def normalize(record: dict, config: dict) -> Event:
    """把一条异构 Splunk 记录转换成稳定的领域事件。"""

    warnings: list[str] = []
    fields, raw = _merge_raw_fields(record, warnings)
    java_log = parse_java_log(raw)
    request, response = _payloads(fields, java_log, warnings)
    service = str(
        fields.get("appName") or fields.get("app") or fields.get("service") or "unknown"
    )
    service = config.get("service_aliases", {}).get(service, service)
    ids = _identifiers(fields, request, response, raw, java_log, config)
    message = str(fields.get("message") or java_log.message or raw)
    exception = _exception(fields, raw)
    timestamp_value = _first_value(fields, ("_time", "timestamp"))
    timestamp_value = java_log.timestamp if timestamp_value is None else timestamp_value
    timestamp = normalize_time(timestamp_value)
    status_value = _first_value(fields, ("httpStatus", "statusCode", "status"))
    status_value = java_log.http_status if status_value is None else status_value
    if not timestamp:
        warnings.append("事件缺少时间")

    api = fields.get("serviceId") or fields.get("path")
    api = api or fields.get("x_envoy_original_path") or java_log.api or ""
    method = fields.get("IN_METHOD") or fields.get("method") or java_log.method or ""
    direction = _first_value(fields, ("direction", "callDirection", "logDirection"))
    direction = direction or java_log.direction or "unknown"
    peer_service = _first_value(
        fields,
        ("peerService", "peer_service", "targetService", "downstreamService"),
    )
    peer_service = peer_service or java_log.peer_service or ""
    call_id = fields.get("callId") or fields.get("spanId")
    call_id = call_id or ids.get("x_b3_spanid") or ""
    parent_call_id = fields.get("parentCallId") or fields.get("parentSpanId")
    parent_call_id = parent_call_id or ids.get("x_b3_parentspanid") or ""
    business_code = _business_code(fields, response)
    source = {
        key: fields[key]
        for key in ("index", "source", "sourcetype", "_cd", "_bkt")
        if key in fields
    }

    return Event(
        id=_event_id(record),
        timestamp=timestamp,
        service=service,
        instance=str(fields.get("pod") or fields.get("host") or ""),
        ids=ids,
        correlation_ids=_correlation_ids(ids, service, config),
        api=str(api),
        method=str(method),
        direction=str(direction).lower(),
        kind=_event_kind(fields, java_log, exception, request, response, message),
        level=str(fields.get("level") or java_log.level or "").upper(),
        message=message,
        request=request,
        response=response,
        http_status=parse_http_status(status_value, warnings),
        business_code=str(business_code) if business_code is not None else None,
        exception=exception,
        peer_service=str(peer_service),
        call_id=str(call_id),
        parent_call_id=str(parent_call_id),
        attempt=str(fields.get("attempt") or fields.get("x_envoy_attempt_count") or ""),
        source=source,
        parse_warnings=warnings,
    )
