import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  FileInput,
  FileOutput,
  Logs,
} from "lucide-react";
import type {
  JourneyNode,
  JourneyStatus,
  OpenEvidence,
  TransactionJourney as Journey,
} from "../../types";

const statusLabels: Record<JourneyStatus, string> = {
  success: "正常",
  failed: "发现错误",
  affected: "受错误影响",
  warning: "证据不完整",
  unknown: "待确认",
};

function StatusIcon({ status }: { status: JourneyStatus }) {
  if (status === "success") return <CheckCircle2 size={15} />;
  if (status === "failed" || status === "affected" || status === "warning") {
    return <CircleAlert size={15} />;
  }
  return <CircleDashed size={15} />;
}

function EvidenceActions({
  node,
  openEvidence,
}: {
  node: JourneyNode;
  openEvidence: OpenEvidence;
}) {
  const requestId = node.request_ids[0];
  const responseId = node.response_ids[0];
  const rawId = node.evidence_ids[0];
  return (
    <div className="journey-node-actions">
      {requestId && (
        <button onClick={() => openEvidence(requestId, "request")}>
          <FileInput size={13} /> Request
        </button>
      )}
      {responseId && (
        <button onClick={() => openEvidence(responseId, "response")}>
          <FileOutput size={13} /> Response
        </button>
      )}
      {rawId && (
        <button onClick={() => openEvidence(rawId, "raw")}>
          <Logs size={13} /> 原始证据
        </button>
      )}
    </div>
  );
}

function JourneyNodeCard({
  node,
  openEvidence,
  highlighted,
}: {
  node: JourneyNode;
  openEvidence: OpenEvidence;
  highlighted: boolean;
}) {
  return (
    <article
      className={`journey-node ${node.status} ${highlighted ? "highlighted" : ""}`}
    >
      <div className="journey-node-heading">
        <strong>{node.service || "服务未知"}</strong>
        <span className={`journey-status ${node.status}`}>
          <StatusIcon status={node.status} />
          {statusLabels[node.status]}
        </span>
      </div>
      <code>
        {node.method ? `${node.method} ` : ""}
        {node.api || "API 未识别"}
      </code>
      {node.failure_reasons.length > 0 && (
        <p>{node.failure_reasons.join("；")}</p>
      )}
      {node.missing_response && <p>已找到请求，暂未找到可配对响应</p>}
      {node.pairing_ambiguous && <p>请求/响应配对存在歧义</p>}
      {node.role === "unknown" && <p>服务角色待配置，暂列在 CM 区域</p>}
      <EvidenceActions node={node} openEvidence={openEvidence} />
    </article>
  );
}

function EmptyStage() {
  return (
    <div className="journey-empty">
      <CircleDashed size={16} />
      当前日志没有识别到该区域的调用
    </div>
  );
}

export default function TransactionJourney({
  journey,
  openEvidence,
}: {
  journey?: Journey;
  openEvidence: OpenEvidence;
}) {
  if (!journey?.stages.length) {
    return (
      <section className="journey-overview">
        <p className="muted">当前报告还没有生成标准化交易链路。</p>
      </section>
    );
  }

  const attribution = journey.attribution;
  const confidenceLabels: Record<string, string> = {
    high: "高",
    medium: "中",
    low: "低",
  };
  return (
    <section className="journey-overview">
      <div className="journey-title">
        <div>
          <span className="eyebrow">TRANSACTION JOURNEY</span>
          <h3>交易链路定位</h3>
        </div>
        <span className={`fault-domain ${attribution.domain}`}>
          {attribution.label}
        </span>
      </div>
      <div className={`fault-summary ${attribution.domain}`}>
        <strong>{attribution.summary}</strong>
        <span>
          归因可信度：{confidenceLabels[attribution.confidence] ?? "未知"} ·{" "}
          {attribution.caution}
        </span>
      </div>
      <div className="journey-stages">
        {journey.stages.map((stage, index) => (
          <div className="journey-stage-wrap" key={stage.id}>
            {index > 0 && (
              <div className="journey-arrow" aria-hidden="true">
                <ArrowRight size={19} />
              </div>
            )}
            <section className={`journey-stage ${stage.status}`}>
              <header>
                <div>
                  <strong>{stage.label}</strong>
                  <span>{stage.description}</span>
                </div>
                <span className={`journey-status ${stage.status}`}>
                  <StatusIcon status={stage.status} />
                  {statusLabels[stage.status]}
                </span>
              </header>
              <div className="journey-stage-nodes">
                {stage.nodes.length === 0 && <EmptyStage />}
                {stage.nodes.map((node) => (
                  <JourneyNodeCard
                    key={node.id}
                    node={node}
                    openEvidence={openEvidence}
                    highlighted={node.id === attribution.node_id}
                  />
                ))}
              </div>
            </section>
          </div>
        ))}
      </div>
    </section>
  );
}
