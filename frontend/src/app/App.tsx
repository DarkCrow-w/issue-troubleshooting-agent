import { useState } from "react";
import { SquarePen } from "lucide-react";
import InvestigationForm from "../features/investigations/components/InvestigationForm";
import ReportPanel from "../features/investigations/components/ReportPanel";
import EvidenceDrawer from "../features/investigations/components/EvidenceDrawer";
import { useInvestigation } from "../features/investigations/hooks/useInvestigation";
import { useEvidence } from "../features/investigations/hooks/useEvidence";
import type { InvestigationRequest } from "../features/investigations/types";

export default function App() {
  const { config, task, taskId, busy, error, submit, cancelTask } =
    useInvestigation();
  const { evidence, openEvidence, closeEvidence } = useEvidence(taskId);
  const [submitted, setSubmitted] = useState<InvestigationRequest | null>(null);

  async function investigate(request: InvestigationRequest) {
    setSubmitted(request);
    await submit(request);
  }

  return (
    <div className="app-shell">
      <header className="topbar" inert={!!evidence}>
        <a href="/" className="brand">
          IssueTroubleshooting <span>交易排查助手</span>
        </a>
        <button
          className="new-chat"
          disabled={busy}
          onClick={() => window.location.assign("/")}
          title="开始新的排查"
        >
          <SquarePen size={18} />
          <span>新排查</span>
        </button>
      </header>
      <main className={taskId ? "conversation" : "welcome"} inert={!!evidence}>
        {!taskId && (
          <div className="welcome-heading">
            <h1>这笔交易，哪里出了问题？</h1>
            <p>输入关联 ID 或 Splunk SPL，从日志中找到答案。</p>
          </div>
        )}
        {taskId && (
          <div className="conversation-content">
            <div className="user-message">
              <span>排查交易</span>
              <code>{submitted?.correlation_id || "自定义 Splunk SPL"}</code>
              {submitted?.question && <p>{submitted.question}</p>}
            </div>
            <ReportPanel
              key={taskId}
              task={task}
              taskId={taskId}
              busy={busy}
              openEvidence={openEvidence}
              onCancel={cancelTask}
            />
          </div>
        )}
        <div className="composer-area">
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <InvestigationForm
            config={config}
            busy={busy}
            onSubmit={investigate}
          />
          <p className="composer-hint">
            {config?.source_mode === "replay" ? "演示日志" : "Splunk"} ·{" "}
            {config?.model_mode === "offline"
              ? "规则分析"
              : config?.model || "连接中"}{" "}
            · 结论可回查原始证据
          </p>
        </div>
      </main>
      <EvidenceDrawer evidence={evidence} onClose={closeEvidence} />
    </div>
  );
}
