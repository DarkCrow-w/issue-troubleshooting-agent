import { FileDown, LoaderCircle, Square } from "lucide-react";
import ReportContent from "./report/ReportContent";
import type { OpenEvidence, Task } from "../types";

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "排查中",
  completed: "已完成",
  partial: "部分完成",
  failed: "执行失败",
  cancelled: "已取消",
};

type Props = {
  task: Task | null;
  taskId: string;
  busy: boolean;
  openEvidence: OpenEvidence;
  onCancel: () => void;
};

function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function ExportActions({ task }: { task: Task | null }) {
  const report = task?.report;
  if (!report) return null;
  const exportMarkdown = () =>
    download("investigation.md", report.markdown, "text/markdown");
  const exportJson = () =>
    download(
      "investigation.json",
      JSON.stringify(task, null, 2),
      "application/json",
    );
  return (
    <>
      <button onClick={exportMarkdown}>
        <FileDown size={15} />
        Markdown
      </button>
      <button onClick={exportJson}>JSON</button>
    </>
  );
}

function ResultHeader({
  task,
  busy,
  onCancel,
}: Pick<Props, "task" | "busy" | "onCancel">) {
  const status = task?.status || "queued";
  return (
    <div className="result-heading">
      <div className="section-heading">
        <h2>IssueTroubleshooting</h2>
        <span className={`status ${status}`}>{statusLabels[status]}</span>
      </div>
      <div className="result-actions">
        {busy && (
          <button onClick={onCancel}>
            <Square size={13} />
            取消
          </button>
        )}
        <ExportActions task={task} />
      </div>
    </div>
  );
}

function Progress({
  task,
  taskId,
  busy,
}: Pick<Props, "task" | "taskId" | "busy">) {
  if (!busy) return null;
  return (
    <div className="progress-line" role="status">
      <LoaderCircle size={15} className="spin" />
      {task?.phase || "任务已提交"}
      <code>{taskId.slice(0, 8)}</code>
    </div>
  );
}

// 主组件只组合任务状态和报告；各标签页的数据展示放在 report/ 内。
export default function ReportPanel({
  task,
  taskId,
  busy,
  openEvidence,
  onCancel,
}: Props) {
  const report = task?.report;
  return (
    <section className="results">
      <ResultHeader task={task} busy={busy} onCancel={onCancel} />
      <Progress task={task} taskId={taskId} busy={busy} />
      {report && (
        <ReportContent
          report={report}
          usage={task.usage}
          openEvidence={openEvidence}
        />
      )}
    </section>
  );
}
