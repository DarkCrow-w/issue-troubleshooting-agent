import { Check, ChevronRight, CircleHelp } from "lucide-react";
import type { Claim, OpenEvidence, Report } from "../../types";
const confidenceLabels: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

// 证据按钮共用一处，事实和反对证据不会出现不同的跳转逻辑。
function EvidenceLinks({
  ids,
  openEvidence,
}: {
  ids: string[];
  openEvidence: OpenEvidence;
}) {
  return ids.map((id) => (
    <button key={id} onClick={() => openEvidence(id)}>
      证据 {id.slice(-6)} <ChevronRight size={12} />
    </button>
  ));
}

function ClaimRow({
  claim,
  hypothesis,
  openEvidence,
}: {
  claim: Claim;
  hypothesis: boolean;
  openEvidence: OpenEvidence;
}) {
  const Icon = hypothesis ? CircleHelp : Check;
  const counterEvidence = claim.counter_evidence_ids ?? [];
  return (
    <div className="claim">
      <div className={`claim-icon ${hypothesis ? "hypothesis" : ""}`}>
        <Icon size={16} />
      </div>
      <div>
        <p>{claim.statement}</p>
        <div className="evidence-links">
          <span>{confidenceLabels[claim.confidence] ?? "未知"}可信度</span>
          <EvidenceLinks ids={claim.evidence_ids} openEvidence={openEvidence} />
        </div>
        {claim.verification && <small>验证方式：{claim.verification}</small>}
        {counterEvidence.length > 0 && (
          <div className="evidence-links">
            反对证据：
            <EvidenceLinks ids={counterEvidence} openEvidence={openEvidence} />
          </div>
        )}
      </div>
    </div>
  );
}

function ClaimList({
  items,
  hypothesis = false,
  emptyMessage,
  openEvidence,
}: {
  items: Claim[];
  hypothesis?: boolean;
  emptyMessage?: string;
  openEvidence: OpenEvidence;
}) {
  // 空结果先返回，并让上层说清是“证据不足”还是“模型失败”。
  if (!items.length) {
    const message = emptyMessage ?? "暂无可确认的失败事实。";
    return <p className="muted">{message}</p>;
  }
  return items.map((claim, index) => (
    <ClaimRow
      key={index}
      claim={claim}
      hypothesis={hypothesis}
      openEvidence={openEvidence}
    />
  ));
}

function EarliestFailure({
  failure,
  openEvidence,
}: {
  failure: Report["earliest_observed_failure"];
  openEvidence: OpenEvidence;
}) {
  if (!failure) return null;
  return (
    <p>
      最早观测到的失败：
      <button onClick={() => openEvidence(failure.event_id)}>
        {failure.service}
        <ChevronRight size={13} />
      </button>
      <small>观测顺序不等同于根因顺序</small>
    </p>
  );
}

function Suggestions({
  items,
  unknown = false,
}: {
  items: string[];
  unknown?: boolean;
}) {
  if (!items.length) return null;
  return (
    <div className={unknown ? "unknown-box" : undefined}>
      <h4>
        {unknown && <CircleHelp size={16} />}
        {unknown ? "仍需确认" : "下一步建议"}
      </h4>
      <ul>
        {items.map((text, index) => (
          <li key={index}>{text}</li>
        ))}
      </ul>
    </div>
  );
}

export default function DiagnosisView({
  report,
  openEvidence,
}: {
  report: Report;
  openEvidence: OpenEvidence;
}) {
  const modelFailed = report.warnings.some((warning) =>
    warning.startsWith("模型"),
  );
  const emptyHypothesisMessage = modelFailed
    ? "模型分析未完成；规则定位结果仍可使用，具体原因见结果限制。"
    : "现有证据还不足以形成可验证的根因假设。";
  return (
    <>
      <div className="summary-card">
        <h3>{report.summary}</h3>
        <EarliestFailure
          failure={report.earliest_observed_failure}
          openEvidence={openEvidence}
        />
      </div>
      <h4>
        观测事实 <span>{report.findings.length}</span>
      </h4>
      <ClaimList items={report.findings} openEvidence={openEvidence} />
      <h4>
        根因假设 <span>{report.hypotheses.length}</span>
      </h4>
      <ClaimList
        items={report.hypotheses}
        hypothesis
        emptyMessage={emptyHypothesisMessage}
        openEvidence={openEvidence}
      />
      <Suggestions items={report.unknowns} unknown />
      <Suggestions items={report.next_steps} />
    </>
  );
}
