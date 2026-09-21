"""解析公司 Java 日志正文中 Splunk 没有拆出的关键字段。"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

LOG_PREFIX = re.compile(
    r"^#\[(?P<time>[^]]+)]\s+\[(?P<context>[^]]*)].*?"
    r"\]\s+(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+"
    r"(?P<logger>\S+)\s+-\s+message=(?P<message>.*)$",
    re.DOTALL,
)
CONTEXT_FIELD = re.compile(r"(?P<key>[A-Za-z][\w.-]*)=(?P<value>[^\s\]]*)")
URL = re.compile(
    r"(?:url\s+is\s*\[\s*|\bapi\s*:\s*)(?P<url>https?://[^\s,\]]+)",
    re.IGNORECASE,
)
HTTP_STATUS = re.compile(r"status\s+code\s*\[\s*(?P<status>\d{3})", re.IGNORECASE)
METHOD = re.compile(r"(?:\bmethod\s*:|\bIN_METHOD=)\s*(?P<method>[A-Z]+)")

IDENTIFIER_PATTERNS = {
    "x_b3_spanid": re.compile(r"\bx-b3-spanid\s*[=:]\s*(?P<value>[\w.-]+)", re.IGNORECASE),
    "x_b3_parentspanid": re.compile(
        r"\bx-b3-parentspanid\s*[=:]\s*(?P<value>[\w.-]+)", re.IGNORECASE
    ),
    "x_b3_traceid": re.compile(r"\bx-b3-traceid\s*[=:]\s*(?P<value>[\w.-]+)", re.IGNORECASE),
    "x_request_id": re.compile(r"\bx-request-id\s*[=:]\s*(?P<value>[\w.-]+)", re.IGNORECASE),
    "x_hsbc_request_correlation_id": re.compile(
        r"\bx-hsbc-request-correlation-id\s*[=:]\s*(?P<value>[\w.:/-]+)", re.IGNORECASE
    ),
    "traceparent": re.compile(r"\btraceparent\s*[=:]\s*(?P<value>[\w-]+)", re.IGNORECASE),
}


@dataclass
class JavaLogDetails:
    timestamp: str = ""
    level: str = ""
    logger: str = ""
    message: str = ""
    kind: str = ""
    direction: str = "unknown"
    api: str = ""
    method: str = ""
    peer_service: str = ""
    http_status: int | None = None
    request: Any = None
    response: Any = None
    identifiers: dict[str, str] = field(default_factory=dict)


def _json_after_marker(text: str, markers: tuple[str, ...]) -> Any:
    """从日志标记后寻找第一个 JSON；由 JSONDecoder 判断真实结束位置。"""

    lowered = text.lower()
    for marker in markers:
        position = lowered.find(marker.lower())
        if position < 0:
            continue
        start = text.find("{", position + len(marker))
        if start < 0:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(text, start)
            return value
        except json.JSONDecodeError:
            continue
    return None


def _transport(message: str) -> tuple[str, str]:
    if re.search(r"\bsend\s+(?:req|request)\b", message, re.IGNORECASE):
        return "request", "outbound"
    if re.search(r"\brequest\s+is\b", message, re.IGNORECASE):
        return "request", "inbound"
    if re.search(r"\breceive\s+(?:res|response)\b", message, re.IGNORECASE):
        return "response", "inbound"
    if re.search(r"\bresponse\s+is\b", message, re.IGNORECASE):
        return "response", "outbound"
    return "", "unknown"


def _url_details(text: str) -> tuple[str, str]:
    match = URL.search(text)
    if not match:
        return "", ""
    parsed = urlparse(match.group("url"))
    api = parsed.path or match.group("url")
    peer = (parsed.hostname or "").split(".", 1)[0]
    return api, peer


def parse_java_log(raw: Any) -> JavaLogDetails:
    if not isinstance(raw, str):
        return JavaLogDetails()

    prefix = LOG_PREFIX.match(raw)
    context = prefix.group("context") if prefix else ""
    message = prefix.group("message") if prefix else raw
    identifiers = {
        match.group("key"): match.group("value")
        for match in CONTEXT_FIELD.finditer(context)
        if match.group("value") not in ("", "<null>")
    }
    for name, pattern in IDENTIFIER_PATTERNS.items():
        match = pattern.search(raw)
        if match:
            identifiers.setdefault(name, match.group("value"))

    # comet gateway 会把 correlationId 写成 correlationId:[...]，不在标准上下文块中。
    bracketed = re.search(r"\bcorrelationId\s*:\s*\[(?P<value>[\w.:/-]+)]", raw)
    if bracketed:
        identifiers.setdefault("correlationId", bracketed.group("value"))

    kind, direction = _transport(message)
    api, peer = _url_details(message)
    status = HTTP_STATUS.search(message)
    method = METHOD.search(message)
    request = (
        _json_after_marker(message, ("body is", "request is"))
        if kind == "request"
        else None
    )
    response = (
        _json_after_marker(message, ("body is", "response is"))
        if kind == "response"
        else None
    )
    return JavaLogDetails(
        timestamp=prefix.group("time") if prefix else "",
        level=prefix.group("level") if prefix else "",
        logger=prefix.group("logger") if prefix else "",
        message=message,
        kind=kind,
        direction=direction,
        api=api,
        method=method.group("method") if method else "",
        peer_service=peer,
        http_status=int(status.group("status")) if status else None,
        request=request,
        response=response,
        identifiers=identifiers,
    )
