import { LoaderCircle, ShieldCheck, X } from "lucide-react";
import type { EvidenceView } from "../hooks/useEvidence";

type EvidenceData = {
  event?: {
    timestamp?: string;
    service?: string;
    api?: string;
    component?: string;
    request?: unknown;
    response?: unknown;
    http_status?: number;
    business_code?: string;
  };
  record?: unknown;
};

const focusLabels = {
  request: "Request",
  response: "Response",
  raw: "日志证据",
};

// 三种互斥状态分别提前返回，抽屉布局不再嵌套错误/加载/内容判断。
function EvidenceBody({ evidence }: { evidence: EvidenceView }) {
  if (evidence.error) return <p className="error">{evidence.error}</p>;
  if (evidence.data === undefined) return <LoaderCircle className="spin" />;

  if (evidence.focus === "raw") {
    return <pre className="evidence-json">{JSON.stringify(evidence.data, null, 2)}</pre>;
  }

  const data = evidence.data as EvidenceData;
  const event = data.event ?? {};
  const payload = evidence.focus === "request" ? event.request : event.response;
  return (
    <div className="focused-evidence">
      <dl>
        <div>
          <dt>服务</dt>
          <dd>{event.service || "未知"}</dd>
        </div>
        <div>
          <dt>API</dt>
          <dd>{event.api || "未知"}</dd>
        </div>
        <div>
          <dt>时间</dt>
          <dd>{event.timestamp || "未知"}</dd>
        </div>
        {event.component && (
          <div>
            <dt>内部步骤</dt>
            <dd>{event.component}</dd>
          </div>
        )}
      </dl>
      {payload === null || payload === undefined ? (
        <p className="muted">该条证据中没有提取到 {focusLabels[evidence.focus]} 内容。</p>
      ) : (
        <pre className="evidence-json">{JSON.stringify(payload, null, 2)}</pre>
      )}
      <details className="raw-evidence">
        <summary>查看完整日志证据</summary>
        <pre className="evidence-json">{JSON.stringify(evidence.data, null, 2)}</pre>
      </details>
    </div>
  );
}

export default function EvidenceDrawer({
  evidence,
  onClose,
}: {
  evidence: EvidenceView | null;
  onClose: () => void;
}) {
  if (!evidence) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <section
        className="evidence-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="日志证据"
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <div>
            <span className="eyebrow">SOURCE EVIDENCE</span>
            <h2>{focusLabels[evidence.focus]}</h2>
            <code>{evidence.id}</code>
          </div>
          <button aria-label="关闭证据" autoFocus onClick={onClose}>
            <X size={22} />
          </button>
        </header>
        <p className="security">
          <ShieldCheck size={15} />
          原始日志 · 未做字段替换
        </p>
        <EvidenceBody evidence={evidence} />
      </section>
    </div>
  );
}
