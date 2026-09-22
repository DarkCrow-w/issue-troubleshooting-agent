"""把底层调用图整理成用户可读的三段交易链路。"""

import json
import re

from troubleshooter.domain.models import Event

from .lifecycle import analyze_call_lifecycle

STAGE_META = {
    "upstream": ("上游", "请求进入 CM 前的调用方与入口数据"),
    "cm": ("CM 内部", "CM 服务内部处理与服务间调用"),
    "downstream": ("下游", "CM 发起的外部 API 调用"),
}
ATTRIBUTION_LABELS = {
    "upstream": "上游输入 / 入口处理",
    "cm": "CM 内部处理 / 调用",
    "downstream": "下游 API 调用",
    "unknown": "故障位置待确认",
}


def _matches(service: str, patterns: list[str]) -> bool:
    """配置错误不应中断整笔排查；无效正则只按普通文本匹配。"""
    for pattern in patterns:
        try:
            if re.search(pattern, service, re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in service.lower():
                return True
    return False


def _configured_role(service: str, config: dict) -> str:
    topology = config.get("topology", {})
    exact_roles = topology.get("service_roles", {})
    role = exact_roles.get(service, "")
    if role in STAGE_META:
        return role
    if service in config.get("composite_id_services", []):
        return "cm"

    pattern_keys = {
        "upstream": "upstream_service_patterns",
        "cm": "cm_service_patterns",
        "downstream": "downstream_service_patterns",
    }
    for candidate, key in pattern_keys.items():
        if _matches(service, topology.get(key, [])):
            return candidate
    return "unknown"


def _is_downstream_call(node: dict, config: dict) -> bool:
    peer = node.get("peer_service", "")
    peer_role = _configured_role(peer, config) if peer else "unknown"
    external_peer = bool(peer) and peer_role not in ("cm", "upstream")
    api_match = _matches(
        node.get("api", ""),
        config.get("topology", {}).get("downstream_api_patterns", []),
    )
    return external_peer or api_match


def _is_upstream_input_failure(
    event: Event | None,
    node: dict,
    incoming: set[str],
    reasons: list[str],
    config: dict,
) -> bool:
    if node["id"] in incoming or event is None:
        return False
    if event.kind == "request":
        return True

    exception = event.exception or {}
    material = " ".join(
        (
            event.message,
            str(exception.get("type", "")),
            str(exception.get("message", "")),
            json.dumps(event.response, ensure_ascii=False, default=str),
            " ".join(reasons),
        )
    )
    patterns = config.get("topology", {}).get("upstream_input_error_patterns", [])
    return _matches(material, patterns)


def _reachable(start: str, targets: set[str], adjacency: dict[str, set[str]]) -> bool:
    pending = [start]
    visited = set()
    while pending:
        current = pending.pop()
        if current in targets:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, set()) - visited)
    return False


def _assign_roles(nodes: list[dict], edges: list[dict], config: dict) -> dict[str, str]:
    roles = {
        node["id"]: _configured_role(node.get("service", ""), config) for node in nodes
    }
    cm_nodes = {node_id for node_id, role in roles.items() if role == "cm"}
    forward: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    for edge in edges:
        forward.setdefault(edge["source"], set()).add(edge["target"])
        reverse.setdefault(edge["target"], set()).add(edge["source"])

    # 未显式配置的服务，用它在 CM 节点前后的位置判断角色。
    # 没有可证实的边时保持 unknown，避免把数组顺序误当成调用关系。
    for node_id, role in list(roles.items()):
        if role != "unknown":
            continue
        if _reachable(node_id, cm_nodes, forward):
            roles[node_id] = "upstream"
        elif _reachable(node_id, cm_nodes, reverse):
            roles[node_id] = "downstream"
    return roles


def _display_node(
    node: dict,
    role: str,
    events_by_id: dict[str, Event],
    failure_by_event: dict[str, dict],
) -> dict:
    lifecycle = analyze_call_lifecycle(node, events_by_id, failure_by_event)
    return {
        "id": node["id"],
        "service": node.get("service", ""),
        "api": node.get("api", ""),
        "method": node.get("method", ""),
        "direction": node.get("direction", "unknown"),
        "peer_service": node.get("peer_service", ""),
        "role": role,
        **lifecycle,
        "evidence_ids": node.get("evidence_ids", []),
        "request_ids": node.get("request_ids", []),
        "response_ids": node.get("response_ids", []),
        "missing_response": bool(node.get("missing_response")),
        "pairing_ambiguous": bool(node.get("pairing_ambiguous")),
        "virtual": False,
    }


def _entry_boundary(nodes: list[dict], incoming: set[str]) -> dict | None:
    entry = next(
        (node for node in nodes if node["role"] == "cm" and node["id"] not in incoming),
        None,
    )
    if entry is None:
        entry = next((node for node in nodes if node["role"] == "cm"), None)
    if entry is None:
        return None
    return {
        "id": "boundary-upstream",
        "service": "上游系统",
        "api": entry["api"],
        "method": entry["method"],
        "direction": "inbound",
        "peer_service": entry["service"],
        "role": "upstream",
        "status": "success" if entry["request_ids"] else "unknown",
        "failure_reasons": [],
        "failure_phase": "",
        "failure_phase_label": "",
        "phases": {
            "request": {
                "status": "success" if entry["request_ids"] else "unknown",
                "evidence_ids": entry["request_ids"],
            },
            "request_processing": {"status": "unknown", "evidence_ids": []},
            "response": {
                "status": "success" if entry["response_ids"] else "unknown",
                "evidence_ids": entry["response_ids"],
            },
            "response_processing": {"status": "unknown", "evidence_ids": []},
        },
        "evidence_ids": entry["request_ids"] + entry["response_ids"],
        "request_ids": entry["request_ids"],
        "response_ids": entry["response_ids"],
        "missing_response": False,
        "pairing_ambiguous": False,
        "virtual": True,
    }


def _external_peer_nodes(nodes: list[dict], config: dict) -> list[dict]:
    peers = []
    for node in nodes:
        peer = node.get("peer_service", "")
        if node["role"] != "cm" or not _is_downstream_call(node, config):
            continue
        peer_node = {
            **node,
            "id": f"peer-{node['id']}",
            "service": peer or "下游服务（名称未识别）",
            "role": "downstream",
            "virtual": True,
        }
        # 响应已经成功返回时，后续异常属于调用方的本地处理。
        # 下游虚拟节点只代表边界上的请求和响应，不能复制调用方的处理失败。
        if node.get("failure_phase") == "response_processing":
            response_status = node["phases"]["response"]["status"]
            peer_node["status"] = (
                "success" if response_status == "success" else "unknown"
            )
            peer_node["failure_reasons"] = []
            peer_node["failure_phase"] = ""
            peer_node["failure_phase_label"] = ""
            peer_node["phases"] = {
                **node["phases"],
                "response_processing": {"status": "unknown", "evidence_ids": []},
            }
        peers.append(peer_node)
    return peers


def _no_failure_attribution() -> dict:
    return {
        "domain": "none",
        "label": "未观测到明确失败",
        "summary": "当前日志没有出现异常、HTTP 错误或非成功业务码。",
        "confidence": "low",
        "node_id": "",
        "evidence_ids": [],
        "phase": "",
        "phase_label": "",
        "caution": "未观测到失败不等同于交易成功，仍受日志覆盖范围限制。",
    }


def _cm_failure_location(
    node: dict,
    event: Event | None,
    edges: list[dict],
    reasons: list[str],
    config: dict,
) -> tuple[str, str, str]:
    """返回故障域、可信度和前端应高亮的节点。"""

    phase = node.get("failure_phase", "unknown")
    if phase == "response_processing":
        return "cm", "high", node["id"]
    if _is_downstream_call(node, config):
        if phase == "response":
            return "downstream", "high", f"peer-{node['id']}"
        # 请求发出后未收到响应，无法区分本地、网络和下游故障。
        return "unknown", "low", node["id"]

    incoming = {edge["target"] for edge in edges}
    upstream_failure = _is_upstream_input_failure(
        event, node, incoming, reasons, config
    )
    if upstream_failure:
        return "upstream", "medium", "boundary-upstream"
    return "cm", "medium", node["id"]


def _fault_attribution(
    events: list[Event],
    nodes: list[dict],
    edges: list[dict],
    earliest: dict | None,
    config: dict,
) -> dict:
    if earliest is None:
        return _no_failure_attribution()

    event_id = earliest["event_id"]
    node = next(
        (item for item in nodes if event_id in item.get("evidence_ids", [])), None
    )
    event = next((item for item in events if item.id == event_id), None)
    role = node["role"] if node else "unknown"
    phase = node.get("failure_phase", "unknown") if node else "unknown"
    phase_label = node.get("failure_phase_label", "未知阶段") if node else "未知阶段"

    domain = role
    node_id = node["id"] if node else ""
    confidence = "high" if role in ("upstream", "downstream") else "medium"
    if role == "cm" and node:
        domain, confidence, node_id = _cm_failure_location(
            node, event, edges, earliest["reasons"], config
        )

    return {
        "domain": domain,
        "label": ATTRIBUTION_LABELS.get(domain, ATTRIBUTION_LABELS["unknown"]),
        "summary": f"最早失败出现在 {earliest['service']} {earliest['api'] or '未知 API'}"
        f"的{phase_label}：" + "；".join(earliest["reasons"]),
        "confidence": confidence,
        "node_id": node_id,
        "evidence_ids": [event_id],
        "reasons": earliest["reasons"],
        "phase": phase,
        "phase_label": phase_label,
        "caution": "这里标记的是最早观测到的故障位置，不等同于最终根因。",
    }


def _stage_status(nodes: list[dict], fault_domain: str, stage_id: str) -> str:
    if fault_domain == stage_id:
        return "failed"
    statuses = {node["status"] for node in nodes}
    if "failed" in statuses:
        return "failed"
    if "affected" in statuses:
        return "affected"
    if "warning" in statuses:
        return "warning"
    if nodes and statuses <= {"success"}:
        return "success"
    return "unknown"


def _mark_propagated_failure(nodes: list[dict], attribution: dict) -> None:
    """故障归到边界时，CM 节点表示观测/传播错误，不再显示成第二个故障域。"""
    source_node_id = ""
    if attribution["domain"] == "downstream" and attribution["node_id"].startswith(
        "peer-"
    ):
        source_node_id = attribution["node_id"].removeprefix("peer-")
    elif (
        attribution["domain"] == "upstream"
        and attribution["node_id"] == "boundary-upstream"
    ):
        evidence_ids = set(attribution["evidence_ids"])
        source = next(
            (
                node
                for node in nodes
                if node["role"] == "cm"
                and evidence_ids.intersection(node["evidence_ids"])
            ),
            None,
        )
        source_node_id = source["id"] if source else ""

    source = next((node for node in nodes if node["id"] == source_node_id), None)
    if source and source["status"] == "failed":
        source["status"] = "affected"


def transaction_journey(events: list[Event], config: dict, artifacts: dict) -> dict:
    graph = artifacts["trace-reconstruction"]
    failure = artifacts["failure-localization"]
    failure_by_event = {item["event_id"]: item for item in failure["failures"]}
    events_by_id = {event.id: event for event in events}
    roles = _assign_roles(graph["nodes"], graph["edges"], config)
    nodes = [
        _display_node(
            node,
            roles.get(node["id"], "unknown"),
            events_by_id,
            failure_by_event,
        )
        for node in graph["nodes"]
    ]
    incoming = {edge["target"] for edge in graph["edges"]}

    upstream_nodes = [node for node in nodes if node["role"] == "upstream"]
    if not upstream_nodes:
        boundary = _entry_boundary(nodes, incoming)
        if boundary:
            upstream_nodes.append(boundary)
    downstream_nodes = [node for node in nodes if node["role"] == "downstream"]
    if not downstream_nodes:
        downstream_nodes = _external_peer_nodes(nodes, config)

    attribution = _fault_attribution(
        events,
        nodes,
        graph["edges"],
        failure.get("earliest_observed_failure"),
        config,
    )
    _mark_propagated_failure(nodes, attribution)
    if attribution["domain"] == "upstream":
        boundary = next(
            (node for node in upstream_nodes if node["id"] == "boundary-upstream"), None
        )
        if boundary:
            boundary["status"] = "failed"
            boundary["failure_reasons"] = attribution["reasons"]
    grouped = {
        "upstream": upstream_nodes,
        "cm": [node for node in nodes if node["role"] in ("cm", "unknown")],
        "downstream": downstream_nodes,
    }
    stages = []
    for stage_id, stage_nodes in grouped.items():
        label, description = STAGE_META[stage_id]
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "description": description,
                "status": _stage_status(stage_nodes, attribution["domain"], stage_id),
                "nodes": stage_nodes,
            }
        )
    return {
        "stages": stages,
        "attribution": attribution,
        "caution": failure["caution"],
    }
