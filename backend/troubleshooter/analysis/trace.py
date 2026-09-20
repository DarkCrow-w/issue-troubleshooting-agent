"""Deterministic facts: these remain available even if a model is unavailable."""

from collections import defaultdict

from troubleshooter.domain.models import Event

from .ordering import time_key


def trace_reconstruction(events: list[Event], config: dict, artifacts: dict) -> dict:
    nodes = artifacts["request-response"]["calls"]
    # 只有异常日志、没有请求响应的服务也必须保留，避免调用图漏掉真实观测。
    represented = {eid for n in nodes for eid in n["evidence_ids"]}
    nodes = [dict(node, evidence_ids=list(node["evidence_ids"])) for node in nodes]
    nodes_by_call = defaultdict(list)
    for node in nodes:
        if node.get("call_id"):
            nodes_by_call[(node["service"], node["call_id"])].append(node)
    for event in events:
        candidates = nodes_by_call.get((event.service, event.call_id), [])
        if event.id not in represented and len(candidates) == 1:
            candidates[0]["evidence_ids"].append(event.id)
            represented.add(event.id)
    nodes = nodes + [
        {
            "id": e.id,
            "service": e.service,
            "api": e.api,
            "evidence_ids": [e.id],
            "request_ids": [],
            "response_ids": [],
        }
        for e in events
        if e.id not in represented and (e.api or e.exception)
    ]
    event_node = {eid: n["id"] for n in nodes for eid in n["evidence_ids"]}
    node_index = {node["id"]: node for node in nodes}
    calls = defaultdict(list)
    for event in events:
        if event.call_id and event.id in event_node:
            calls[event.call_id].append(event)
    call_nodes = {
        call_id: {event_node[e.id] for e in entries} for call_id, entries in calls.items()
    }
    peers = defaultdict(dict)
    for event in events:
        if event.id in event_node:
            for correlation_id in event.correlation_ids:
                peers[(event.service, correlation_id)][event_node[event.id]] = event.id
    edges = []
    seen = set()
    for child in events:
        if child.id not in event_node:
            continue
        parents = calls.get(child.parent_call_id, []) if child.parent_call_id else []
        parent_nodes = call_nodes.get(child.parent_call_id, set())
        if len(parent_nodes) == 1:
            parent = parents[0]
            source, target = event_node[parent.id], event_node[child.id]
            ambiguous = node_index[source].get("pairing_ambiguous") or node_index[target].get(
                "pairing_ambiguous"
            )
            # 显式父子关系有歧义时直接放弃，不能降级为猜测来绕过歧义检查。
            if source == target or ambiguous:
                continue
            edge = {
                "source": source,
                "target": target,
                "certainty": "confirmed",
                "reason": "显式 parentCallId/parentSpanId 关联",
                "evidence_ids": [parent.id, child.id],
            }
        elif child.peer_service:
            candidate_nodes = {}
            for correlation_id in child.correlation_ids:
                candidate_nodes.update(peers.get((child.peer_service, correlation_id), {}))
            # 仅有目标服务/关联 ID 时，只允许唯一候选，并始终标记为推测。
            if len(candidate_nodes) != 1:
                continue
            target = next(iter(candidate_nodes))
            if event_node[child.id] == target:
                continue
            edge = {
                "source": event_node[child.id],
                "target": target,
                "certainty": "inferred",
                "reason": "目标服务与交易关联匹配，缺少显式父子调用标识",
                "evidence_ids": [child.id, candidate_nodes[target]],
            }
        else:
            continue
        pair = (edge["source"], edge["target"])
        if pair in seen:
            continue
        edges.append(edge)
        seen.add(pair)
    return {
        "nodes": nodes,
        "edges": edges,
        "services": sorted({e.service for e in events}),
        "timeline": [
            {
                "event_id": e.id,
                "timestamp": e.timestamp,
                "service": e.service,
                "api": e.api,
                "kind": e.kind,
            }
            for e in sorted(events, key=time_key)
        ],
    }
