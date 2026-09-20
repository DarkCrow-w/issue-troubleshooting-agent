import { LoaderCircle, ShieldCheck, X } from "lucide-react";
import type { EvidenceView } from "../hooks/useEvidence";

// 三种互斥状态分别提前返回，抽屉布局不再嵌套错误/加载/内容判断。
function EvidenceBody({ evidence }: { evidence: EvidenceView }) {
  if (evidence.error) return <p className="error">{evidence.error}</p>;
  if (evidence.data === undefined) return <LoaderCircle className="spin" />;
  return <pre>{JSON.stringify(evidence.data, null, 2)}</pre>;
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
            <h2>日志证据</h2>
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
