"""根据明确调用标识重建调用关系，不用数组顺序猜测因果。"""

from collections import defaultdict

from troubleshooter.domain.models import Event

from .ordering import time_key


def _attach_related_events(events: list[Event], calls: list[dict]) -> list[dict]:
    """把同一服务、同一调用 ID 的异常日志附到已有调用节点。"""

    nodes = [dict(call, evidence_ids=list(call["evidence_ids"])) for call in calls]
    represented = {event_id for node in nodes for event_id in node["evidence_ids"]}
    nodes_by_call: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for node in nodes:
        if node.get("call_id"):
            nodes_by_call[(node["service"], node["call_id"])].append(node)

    for event in events:
        candidates = nodes_by_call.get((event.service, event.call_id), [])
        if event.id in represented or len(candidates) != 1:
            continue
        candidates[0]["evidence_ids"].append(event.id)
        represented.add(event.id)

    # 只有异常或 API 信息、没有请求响应的日志也必须进入图中。
    nodes.extend(
        {
            "id": event.id,
            "service": event.service,
            "api": event.api,
            "evidence_ids": [event.id],
            "request_ids": [],
            "response_ids": [],
        }
        for event in events
        if event.id not in represented and (event.api or event.exception)
    )
    return nodes


def _events_by_call(
    events: list[Event], event_node: dict[str, str]
) -> dict[str, list[Event]]:
    calls: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.call_id and event.id in event_node:
            calls[event.call_id].append(event)
    return calls


def _peer_candidates(
    events: list[Event], event_node: dict[str, str]
) -> dict[tuple[str, str], dict[str, str]]:
    peers: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for event in events:
        if event.id not in event_node:
            continue
        for correlation_id in event.correlation_ids:
            peers[(event.service, correlation_id)][event_node[event.id]] = event.id
    return peers


def _confirmed_edge(
    child: Event,
    event_node: dict[str, str],
    node_by_id: dict[str, dict],
    events_by_call: dict[str, list[Event]],
    nodes_by_call: dict[str, set[str]],
) -> dict | None:
    if not child.parent_call_id:
        return None
    parent_nodes = nodes_by_call.get(child.parent_call_id, set())
    if len(parent_nodes) != 1:
        return None

    parent = events_by_call[child.parent_call_id][0]
    source = event_node[parent.id]
    target = event_node[child.id]
    ambiguous = node_by_id[source].get("pairing_ambiguous") or node_by_id[target].get(
        "pairing_ambiguous"
    )
    if source == target or ambiguous:
        return None
    return {
        "source": source,
        "target": target,
        "certainty": "confirmed",
        "reason": "显式 parentCallId/parentSpanId 关联",
        "evidence_ids": [parent.id, child.id],
    }


def _inferred_edge(
    child: Event,
    event_node: dict[str, str],
    peers: dict[tuple[str, str], dict[str, str]],
) -> dict | None:
    if not child.peer_service:
        return None
    candidates = {}
    for correlation_id in child.correlation_ids:
        candidates.update(peers.get((child.peer_service, correlation_id), {}))
    # 只有唯一候选时才允许推测，避免同一服务的并发调用被错误串联。
    if len(candidates) != 1:
        return None
    target, target_evidence = next(iter(candidates.items()))
    source = event_node[child.id]
    if source == target:
        return None
    return {
        "source": source,
        "target": target,
        "certainty": "inferred",
        "reason": "目标服务与交易关联匹配，缺少显式父子调用标识",
        "evidence_ids": [child.id, target_evidence],
    }


def _edges(events: list[Event], nodes: list[dict]) -> list[dict]:
    event_node = {
        event_id: node["id"] for node in nodes for event_id in node["evidence_ids"]
    }
    node_by_id = {node["id"]: node for node in nodes}
    events_by_call = _events_by_call(events, event_node)
    nodes_by_call = {
        call_id: {event_node[event.id] for event in entries}
        for call_id, entries in events_by_call.items()
    }
    peers = _peer_candidates(events, event_node)

    edges = []
    seen = set()
    for child in events:
        if child.id not in event_node:
            continue
        has_unique_parent = len(nodes_by_call.get(child.parent_call_id, set())) == 1
        if has_unique_parent:
            edge = _confirmed_edge(
                child, event_node, node_by_id, events_by_call, nodes_by_call
            )
            # 显式关系存在歧义时直接放弃，不能降级成推测关系。
            if edge is None:
                continue
        else:
            edge = _inferred_edge(child, event_node, peers)
        if not edge:
            continue
        pair = (edge["source"], edge["target"])
        if pair in seen:
            continue
        edges.append(edge)
        seen.add(pair)
    return edges


def _timeline(events: list[Event]) -> list[dict]:
    return [
        {
            "event_id": event.id,
            "timestamp": event.timestamp,
            "service": event.service,
            "api": event.api,
            "kind": event.kind,
        }
        for event in sorted(events, key=time_key)
    ]


def trace_reconstruction(events: list[Event], config: dict, artifacts: dict) -> dict:
    nodes = _attach_related_events(events, artifacts["request-response"]["calls"])
    return {
        "nodes": nodes,
        "edges": _edges(events, nodes),
        "services": sorted({event.service for event in events}),
        "timeline": _timeline(events),
    }
