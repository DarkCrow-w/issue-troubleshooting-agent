import {
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  FileInput,
  FileOutput,
  Logs,
  Settings2,
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

const phaseMeta = {
  request: { label: "请求发送", icon: ArrowRight, focus: "request" as const },
  response: { label: "响应返回", icon: ArrowLeft, focus: "response" as const },
  response_processing: {
    label: "响应后处理",
    icon: Settings2,
    focus: "raw" as const,
  },
};

function phaseStatusLabel(phase: string, status: JourneyStatus) {
  if (phase === "response_processing" && status === "success") return "未见异常";
  if (status === "success") return phase === "response" ? "已返回" : "已记录";
  if (status === "failed") return "此处报错";
  if (status === "warning") return "证据不完整";
  return "未观测";
}

function CallPhases({
  node,
  openEvidence,
}: {
  node: JourneyNode;
  openEvidence: OpenEvidence;
}) {
  if (!node.phases) return null;
  return (
    <div className="call-phases" aria-label="调用生命周期">
      {Object.entries(phaseMeta).map(([phaseId, meta]) => {
        const phase = node.phases?.[phaseId as keyof typeof node.phases];
        if (!phase) return null;
        const evidenceId = phase.evidence_ids[0];
        const Icon = meta.icon;
        const content = (
          <>
            <span className="call-phase-name">
              <Icon size={13} /> {meta.label}
            </span>
            <span className={`call-phase-status ${phase.status}`}>
              {phaseStatusLabel(phaseId, phase.status)}
            </span>
          </>
        );
        return evidenceId ? (
          <button
            className={`call-phase ${phase.status}`}
            key={phaseId}
            onClick={() => openEvidence(evidenceId, meta.focus)}
          >
            {content}
          </button>
        ) : (
          <div className={`call-phase ${phase.status}`} key={phaseId}>
            {content}
          </div>
        );
      })}
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
        <p>
          {node.failure_phase_label && `${node.failure_phase_label}：`}
          {node.failure_reasons.join("；")}
        </p>
      )}
      {node.missing_response && <p>已找到请求，暂未找到可配对响应</p>}
      {node.pairing_ambiguous && <p>请求/响应配对存在歧义</p>}
      {node.role === "unknown" && <p>服务角色待配置，暂列在 CM 区域</p>}
      <CallPhases node={node} openEvidence={openEvidence} />
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
      <div className="journey-direction-legend">
        <span><ArrowRight size={14} /> 请求向下游发送</span>
        <span><ArrowLeft size={14} /> 响应向调用方返回</span>
        <span><Settings2 size={14} /> 返回后由当前服务继续处理</span>
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
