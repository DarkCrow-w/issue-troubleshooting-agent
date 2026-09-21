import { useState } from "react";
import { ChevronRight } from "lucide-react";
import CallGraph from "../CallGraph";
import DiagnosisView from "./DiagnosisView";
import ExecutionDetails from "./ExecutionDetails";
import TransactionJourney from "./TransactionJourney";
import type { OpenEvidence, Report, Task } from "../../types";

const tabs = [
  { id: "diagnosis", title: "诊断结论" },
  { id: "chain", title: "调用链路" },
  { id: "timeline", title: "日志时间线" },
  { id: "details", title: "执行详情" },
] as const;
type Tab = (typeof tabs)[number]["id"];
type Props = {
  report: Report;
  usage: Task["usage"];
  openEvidence: OpenEvidence;
};

function Timeline({
  events,
  openEvidence,
}: {
  events: Report["graph"]["timeline"];
  openEvidence: Props["openEvidence"];
}) {
  return (
    <div className="timeline">
      {events.map((event) => {
        // 统一使用业务时区，不能随用户电脑时区改变日志显示顺序的含义。
        const time = new Date(event.timestamp).toLocaleTimeString("zh-CN", {
          timeZone: "Asia/Shanghai",
          fractionalSecondDigits: 3,
        });
        return (
          <button
            key={event.event_id}
            onClick={() => openEvidence(event.event_id)}
          >
            <time>{time}</time>
            <span className={`event-dot ${event.kind}`} />
            <div>
              <strong>{event.service}</strong>
              <span>{event.api || "未识别 API"}</span>
            </div>
            <code>{event.kind}</code>
            <ChevronRight size={15} />
          </button>
        );
      })}
    </div>
  );
}

function ActiveView({
  tab,
  report,
  usage,
  openEvidence,
}: Props & { tab: Tab }) {
  // 一个明确分支只负责选择一个视图，避免在主 return 中堆叠多个判断和大片 JSX。
  switch (tab) {
    case "chain":
      return (
        <CallGraph
          graph={report.graph}
          journey={report.journey}
          openEvidence={openEvidence}
        />
      );
    case "timeline":
      return (
        <Timeline events={report.graph.timeline} openEvidence={openEvidence} />
      );
    case "details":
      return <ExecutionDetails report={report} usage={usage} />;
    default:
      return <DiagnosisView report={report} openEvidence={openEvidence} />;
  }
}

function ReportNotes({ report }: { report: Report }) {
  return (
    <>
      {report.warnings.length > 0 && (
        <div className="warning-list">
          <strong>结果限制</strong>
          {report.warnings.map((text, index) => (
            <p key={index}>{text}</p>
          ))}
        </div>
      )}
      {report.notes.length > 0 && (
        <div className="report-notes">
          {report.notes.map((text, index) => (
            <p key={index}>{text}</p>
          ))}
        </div>
      )}
    </>
  );
}

export default function ReportContent(props: Props) {
  const [tab, setTab] = useState<Tab>("diagnosis");
  return (
    <>
      <TransactionJourney
        journey={props.report.journey}
        openEvidence={props.openEvidence}
      />
      <div className="details-title">
        <span className="eyebrow">DETAILED ANALYSIS</span>
        <h3>详细分析</h3>
      </div>
      <div className="tabs">
        {tabs.map(({ id, title }) => (
          <button
            key={id}
            className={tab === id ? "selected" : ""}
            onClick={() => setTab(id)}
          >
            {title}
          </button>
        ))}
      </div>
      <div className="tab-content">
        <ActiveView tab={tab} {...props} />
      </div>
      <ReportNotes report={props.report} />
    </>
  );
}
