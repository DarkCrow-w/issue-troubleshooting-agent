import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  ExternalLink,
  GitBranch,
} from "lucide-react";
import type {
  CallNode,
  JourneyNode,
  OpenEvidence,
  Report,
} from "../types";

type Graph = Report["graph"];
type Edge = Graph["edges"][number];
type NodeState = "failed" | "affected" | "warning" | "success" | "observed";

interface TreeNode {
  node: CallNode;
  parentEdge?: Edge;
  children: TreeNode[];
}

function wouldCreateCycle(
  edge: Edge,
  parentByTarget: Map<string, Edge>,
): boolean {
  let current = edge.source;
  const visited = new Set<string>();
  while (parentByTarget.has(current) && !visited.has(current)) {
    if (current === edge.target) return true;
    visited.add(current);
    current = parentByTarget.get(current)!.source;
  }
  return current === edge.target;
}

function buildTree(graph: Graph): { roots: TreeNode[]; extraEdges: Edge[] } {
  const nodeIds = new Set(graph.nodes.map((node) => node.id));
  const parentByTarget = new Map<string, Edge>();
  const extraEdges: Edge[] = [];

  // 明确关联优先进入主树；多父关系和环路保留为附加关联，不能静默丢失。
  const edges = [...graph.edges].sort((left, right) => {
    const rightScore = Number(right.certainty === "confirmed");
    const leftScore = Number(left.certainty === "confirmed");
    return rightScore - leftScore;
  });
  for (const edge of edges) {
    const valid = nodeIds.has(edge.source) && nodeIds.has(edge.target);
    const hasParent = parentByTarget.has(edge.target);
    if (!valid || hasParent || wouldCreateCycle(edge, parentByTarget)) {
      if (valid) extraEdges.push(edge);
      continue;
    }
    parentByTarget.set(edge.target, edge);
  }

  const treeNodes = new Map<string, TreeNode>();
  graph.nodes.forEach((node) => treeNodes.set(node.id, { node, children: [] }));
  parentByTarget.forEach((edge, target) => {
    const parent = treeNodes.get(edge.source);
    const child = treeNodes.get(target);
    if (!parent || !child) return;
    child.parentEdge = edge;
    parent.children.push(child);
  });

  return {
    roots: graph.nodes
      .filter((node) => !parentByTarget.has(node.id))
      .map((node) => treeNodes.get(node.id)!),
    extraEdges,
  };
}

function nodeState(
  node: CallNode,
  journeyNode: JourneyNode | undefined,
  faultNodeId: string,
): NodeState {
  // 只有归因节点叫“故障点”；其他失败状态表示错误沿调用链传播。
  if (node.id === faultNodeId) return "failed";
  if (journeyNode?.status === "failed" || journeyNode?.status === "affected") {
    return "affected";
  }
  if (node.missing_response || node.pairing_ambiguous) return "warning";
  if (journeyNode?.status === "warning" || journeyNode?.status === "unknown") {
    return "warning";
  }
  if (journeyNode?.status === "success") return "success";
  return "observed";
}

const stateLabel: Record<NodeState, string> = {
  failed: "故障点",
  affected: "受影响",
  warning: "待确认",
  success: "正常",
  observed: "已观测",
};

function StateIcon({ state }: { state: NodeState }) {
  if (state === "failed") return <AlertTriangle size={15} />;
  if (state === "success") return <CheckCircle2 size={15} />;
  return <CircleDashed size={15} />;
}

function directionLabel(direction?: string): string {
  if (direction === "inbound") return "接收调用";
  if (direction === "outbound") return "发起调用";
  return "方向未知";
}

function CallCard({
  node,
  journeyNode,
  faultNodeId,
  openEvidence,
}: {
  node: CallNode;
  journeyNode?: JourneyNode;
  faultNodeId: string;
  openEvidence: OpenEvidence;
}) {
  const state = nodeState(node, journeyNode, faultNodeId);
  return (
    <button
      className={`call-node ${state}`}
      onClick={() => openEvidence(node.evidence_ids[0])}
    >
      <span className={`node-state ${state}`}>
        <StateIcon state={state} />
        {stateLabel[state]}
      </span>
      <span className="call-node-copy">
        <strong>{node.service}</strong>
        <code>{node.api || "API 未知"}</code>
        <small>
          {directionLabel(node.direction)} · {node.evidence_ids.length} 条证据
          {node.attempt ? ` · 第 ${node.attempt} 次尝试` : ""}
          {node.missing_response ? " · 未找到响应" : ""}
          {node.pairing_ambiguous ? " · 请求响应配对有歧义" : ""}
        </small>
      </span>
      <ExternalLink size={14} />
    </button>
  );
}

function TreeBranch({
  item,
  journeyNodes,
  faultNodeId,
  openEvidence,
}: {
  item: TreeNode;
  journeyNodes: Map<string, JourneyNode>;
  faultNodeId: string;
  openEvidence: OpenEvidence;
}) {
  return (
    <li className={`call-tree-item ${item.parentEdge?.certainty ?? "root"}`}>
      {item.parentEdge && (
        <span className="edge-kind">
          {item.parentEdge.certainty === "confirmed" ? "明确" : "推测"}
        </span>
      )}
      <CallCard
        node={item.node}
        journeyNode={journeyNodes.get(item.node.id)}
        faultNodeId={faultNodeId}
        openEvidence={openEvidence}
      />
      {item.children.length > 0 && (
        <ul className="call-tree-children">
          {item.children.map((child) => (
            <TreeBranch
              key={child.node.id}
              item={child}
              journeyNodes={journeyNodes}
              faultNodeId={faultNodeId}
              openEvidence={openEvidence}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function ExtraEdges({
  edges,
  nodes,
  openEvidence,
}: {
  edges: Edge[];
  nodes: Map<string, CallNode>;
  openEvidence: OpenEvidence;
}) {
  if (!edges.length) return null;
  return (
    <div className="extra-relations">
      <strong>附加关联</strong>
      <p>以下关系没有放入主树，避免同一调用重复显示。</p>
      {edges.map((edge, index) => (
        <button
          key={`${edge.source}-${edge.target}-${index}`}
          onClick={() => openEvidence(edge.evidence_ids[0])}
        >
          {nodes.get(edge.source)?.service || "未知服务"} →{" "}
          {nodes.get(edge.target)?.service || "未知服务"}
          <small>{edge.reason}</small>
        </button>
      ))}
    </div>
  );
}

export default function CallGraph({
  graph,
  journey,
  openEvidence,
}: {
  graph: Graph;
  journey: Report["journey"];
  openEvidence: OpenEvidence;
}) {
  if (!graph.nodes.length) {
    return <p className="muted">暂无可展示的调用节点。</p>;
  }
  const { roots, extraEdges } = buildTree(graph);
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const journeyNodes = new Map(
    journey.stages.flatMap((stage) => stage.nodes).map((node) => [node.id, node]),
  );

  return (
    <div className="call-graph">
      <div className="graph-summary">
        <GitBranch size={16} />
        <strong>{graph.nodes.length} 个调用节点</strong>
        <span>{graph.edges.length} 条调用关系</span>
      </div>
      <div className="graph-legend">
        <span className="solid-line" /> 明确关联
        <span className="dashed-line" /> 推测关联
        <span className="state-swatch failed" /> 故障点
        <span className="state-swatch affected" /> 受影响
      </div>
      <div className="call-tree">
        <ul className="call-tree-roots">
          {roots.map((root) => (
            <TreeBranch
              key={root.node.id}
              item={root}
              journeyNodes={journeyNodes}
              faultNodeId={journey.attribution.node_id}
              openEvidence={openEvidence}
            />
          ))}
        </ul>
      </div>
      {!graph.edges.length && (
        <p className="muted">缺少可确认的调用边，各节点按独立根节点展示。</p>
      )}
      <ExtraEdges edges={extraEdges} nodes={nodes} openEvidence={openEvidence} />
    </div>
  );
}
