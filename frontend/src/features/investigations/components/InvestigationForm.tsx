import { useEffect, useState } from "react";
import { ArrowUp, LoaderCircle } from "lucide-react";
import type { InvestigationRequest, WorkflowConfig } from "../types";

import InvestigationSettings, {
  type SearchSettings,
} from "./InvestigationSettings";

interface Props {
  config: WorkflowConfig | null;
  busy: boolean;
  onSubmit: (request: InvestigationRequest) => Promise<void>;
}

export default function InvestigationForm({ config, busy, onSubmit }: Props) {
  const [correlationId, setCorrelationId] = useState("demo-transaction-001");
  const [settings, setSettings] = useState<SearchSettings>({
    environment: "demo",
    workflow: "standard",
    startTime: "2026-07-28T16:50",
    endTime: "2026-07-28T16:55",
    cleaning: true,
  });
  const { environment, workflow, startTime, endTime, cleaning } = settings;
  function updateSettings(patch: Partial<SearchSettings>) {
    setSettings((current) => ({ ...current, ...patch }));
  }
  const [question, setQuestion] = useState("");

  useEffect(() => {
    if (!config) return;
    updateSettings({
      environment: config.environments[0] || "",
      workflow: config.workflows[0]?.id || "",
    });
  }, [config]);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    // 页面时间按业务时区提交，避免浏览器本地时区造成检索范围偏移。
    void onSubmit({
      correlation_id: correlationId.trim(),
      environment,
      workflow,
      start_time: `${startTime}:00+08:00`,
      end_time: `${endTime}:00+08:00`,
      cleaning_enabled: cleaning,
      question,
    });
  }
  return (
    <form className="composer" onSubmit={submit}>
      <input
        className="transaction-input"
        aria-label="交易关联 ID"
        required
        value={correlationId}
        onChange={(e) => setCorrelationId(e.target.value)}
        placeholder="输入 seqNo 或 correlationId"
      />
      <textarea
        className="question-input"
        aria-label="补充问题"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="想重点排查什么？（选填）"
        maxLength={2000}
        rows={2}
      />
      <div className="composer-controls">
        <InvestigationSettings
          config={config}
          value={settings}
          onChange={updateSettings}
        />
        <button
          className="send-button"
          aria-label={busy ? "排查进行中" : "开始排查"}
          title="开始排查"
          disabled={!config || busy}
          type="submit"
        >
          {busy ? (
            <LoaderCircle size={20} className="spin" />
          ) : (
            <ArrowUp size={21} />
          )}
        </button>
      </div>
    </form>
  );
}
