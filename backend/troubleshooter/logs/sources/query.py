"""Splunk and local replay implement the same bounded search interface."""

import re

from troubleshooter.domain.models import QuerySpec

BLOCKED_SPL_COMMAND = re.compile(
    r"\|\s*(?:collect|delete|outputlookup|sendemail|script|run|map|rest|"
    r"dbxquery|inputlookup|loadjob|savedsearch|appendcols?|join|union|multisearch)\b",
    re.IGNORECASE,
)


def spl_literal(value: str) -> str:
    # Wildcards are forbidden in identifiers: quoted SPL still interprets '*'.
    if any(char in value for char in ("*", "\n", "\r", "\x00")):
        raise ValueError("查询值不得包含通配符或控制字符")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def split_spl_pipeline(spl: str) -> tuple[str, str]:
    """在引号外找到第一个管道符，避免误切 rex 或字符串里的 ``|``。"""

    quoted = False
    escaped = False
    for index, char in enumerate(spl):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
            continue
        if char == "|" and not quoted:
            return spl[:index].strip(), spl[index:].strip()
    return spl.strip(), ""


def validate_spl(spl: str) -> tuple[str, str]:
    """校验用户 SPL，并拆成基础过滤条件和只读处理管道。"""

    expression = spl.strip()
    if not expression:
        return "", ""
    if "\x00" in expression or "\r" in expression:
        raise ValueError("Splunk SPL 不得包含空字符或回车控制符")
    if "[" in expression or "]" in expression:
        raise ValueError("Splunk SPL 暂不支持子搜索")
    if BLOCKED_SPL_COMMAND.search(expression):
        raise ValueError("Splunk SPL 包含不允许的外部查询或写入命令")
    expression = re.sub(r"^search\s+", "", expression, count=1, flags=re.IGNORECASE)
    return split_spl_pipeline(expression)


def _environment_clause(query: QuerySpec, config: dict) -> str:
    environment = config["environments"].get(query.environment)
    if not environment or not environment.get("indexes"):
        raise ValueError("未配置该环境的 Splunk index")
    indexes = " OR ".join(
        "index=" + spl_literal(index) for index in environment["indexes"]
    )
    return f"({indexes})"


def _identifier_clause(identifier: str, fields: list[str]) -> str:
    value = spl_literal(identifier)
    matches = []
    for field in fields:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", field):
            raise ValueError("关联字段配置不合法")
        matches.append(f"{field}={value}")
    # 裸值用于找到 composite ID，结果归属仍由 EvidenceCollector 严格校验。
    matches.append(value)
    return "(" + " OR ".join(matches) + ")"


def _service_clause(service: str) -> str:
    value = spl_literal(service)
    return f"(appName={value} OR app={value} OR service={value})"


def _instance_clause(instance: str) -> str:
    value = spl_literal(instance)
    return f"(pod={value} OR host={value})"


def build_spl(query: QuerySpec, config: dict) -> str:
    clauses = [_environment_clause(query, config)]
    if query.identifier:
        clauses.append(
            _identifier_clause(query.identifier, config["correlation_fields"])
        )
    if query.service:
        clauses.append(_service_clause(query.service))
    if query.instance:
        clauses.append(_instance_clause(query.instance))
    custom_filter, pipeline = validate_spl(query.spl)
    if custom_filter:
        clauses.append(f"({custom_filter})")
    if (
        not query.identifier
        and not (query.service and query.instance)
        and not query.spl
    ):
        raise ValueError("上下文查询必须限定服务和实例")
    generated = "search " + " AND ".join(clauses)
    return f"{generated} {pipeline}".rstrip()
