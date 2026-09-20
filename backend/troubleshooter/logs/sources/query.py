"""Splunk and local replay implement the same bounded search interface."""

import re

from troubleshooter.domain.models import QuerySpec


def spl_literal(value: str) -> str:
    # Wildcards are forbidden in identifiers: quoted SPL still interprets '*'.
    if any(char in value for char in ("*", "\n", "\r", "\x00")):
        raise ValueError("查询值不得包含通配符或控制字符")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_spl(query: QuerySpec, config: dict) -> str:
    environment = config["environments"].get(query.environment)
    if not environment or not environment.get("indexes"):
        raise ValueError("未配置该环境的 Splunk index")
    indexes = " OR ".join("index=" + spl_literal(index) for index in environment["indexes"])
    clauses = [f"({indexes})"]
    if query.identifier:
        value = spl_literal(query.identifier)
        matches = []
        for field in config["correlation_fields"]:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", field):
                raise ValueError("关联字段配置不合法")
            matches.append(f"{field}={value}")
        # Search broadly enough to find composite IDs; verify exact identity in the engine.
        matches.append(f"{value}")
        clauses.append("(" + " OR ".join(matches) + ")")
    if query.service:
        value = spl_literal(query.service)
        clauses.append(f"(appName={value} OR app={value} OR service={value})")
    if query.instance:
        value = spl_literal(query.instance)
        clauses.append(f"(pod={value} OR host={value})")
    if not query.identifier and not (query.service and query.instance):
        raise ValueError("上下文查询必须限定服务和实例")
    return "search " + " AND ".join(clauses)
