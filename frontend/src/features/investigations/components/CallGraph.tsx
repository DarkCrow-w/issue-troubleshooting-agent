import { ArrowDownRight, CornerDownRight, ExternalLink } from "lucide-react";
import type { CallNode, Report } from "../types";

function CallCard({
  node,
  index,
  openEvidence,
}: {
  node: CallNode;
  index: number;
  openEvidence: (id: string) => void;
}) {
  return (
    <button
      className="call-node"
      onClick={() => openEvidence(node.evidence_ids[0])}
    >
      <span className="node-number">{String(index + 1).padStart(2, "0")}</span>
      <div>
        <strong>{node.service}</strong>
        <code>{node.api || "API 未知"}</code>
        <small>
          {node.evidence_ids.length} 条证据
          {node.attempt ? ` · 第 ${node.attempt} 次尝试` : ""}
          {node.missing_response ? " · 响应待确认" : ""}
          {node.pairing_ambiguous ? " · 配对有歧义" : ""}
        </small>
      </div>
      <ExternalLink size={14} />
    </button>
  );
}

function CallEdges({
  graph,
  openEvidence,
}: {
  graph: Report["graph"];
  openEvidence: (id: string) => void;
}) {
  if (!graph.edges.length)
    return (
      <p className="muted">暂无可确认的调用边。节点顺序不代表调用关系。</p>
    );
  // 使用 ID 查节点；不能根据数组位置推断实际调用关系。
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  return (
    <div className="edges">
      {graph.edges.map((edge, index) => (
        <div className={`edge ${edge.certainty}`} key={index}>
          <CornerDownRight size={17} />
          <span>
            {nodes.get(edge.source)?.service} <ArrowDownRight size={15} />{" "}
            {nodes.get(edge.target)?.service}
          </span>
          <button onClick={() => openEvidence(edge.evidence_ids[0])}>
            {edge.certainty === "confirmed" ? "明确关联" : "推测关联"}
          </button>
          <small>{edge.reason}</small>
        </div>
      ))}
    </div>
  );
}

export default function CallGraph({
  graph,
  openEvidence,
}: {
  graph: Report["graph"];
  openEvidence: (id: string) => void;
}) {
  return (
    <div className="call-graph">
      <div className="graph-legend">
        <span className="dot" /> 已观测调用 <span className="solid-line" />{" "}
        明确关联 <span className="dashed-line" /> 推测关联
      </div>
      <div className="node-grid">
        {graph.nodes.map((node, index) => (
          <CallCard
            key={node.id}
            node={node}
            index={index}
            openEvidence={openEvidence}
          />
        ))}
      </div>
      <CallEdges graph={graph} openEvidence={openEvidence} />
    </div>
  );
}
