import { Terminal } from "lucide-react";
import type { Report, Task } from "../../types";

function Metrics({ report, usage }: { report: Report; usage: Task["usage"] }) {
  // 单位跟随数据定义，渲染时不根据中文标题做多层条件判断。
  const metrics = [
    { title: "观测服务", value: report.graph.services.length, unit: "个" },
    { title: "获取日志", value: usage.events || 0, unit: "条" },
    { title: "执行查询", value: usage.queries || 0, unit: "次" },
    { title: "模型调用", value: usage.model_calls || 0, unit: "次" },
  ];
  return (
    <div className="metrics">
      {metrics.map(({ title, value, unit }) => (
        <div key={title}>
          <span>{title}</span>
          <strong>
            {value}
            <small> {unit}</small>
          </strong>
        </div>
      ))}
    </div>
  );
}

function QueryEntry({ query }: { query: Report["queries"][number] }) {
  return (
    <details className="query">
      <summary>
        <Terminal size={15} />
        {query.reason}
        <span>{query.count} 条</span>
      </summary>
      <pre>{query.spl}</pre>
    </details>
  );
}

export default function ExecutionDetails({
  report,
  usage,
}: {
  report: Report;
  usage: Task["usage"];
}) {
  return (
    <>
      <Metrics report={report} usage={usage} />
      <div className="usage-detail">
        <h4>输入与消耗</h4>
        <p>
          清洗前 {(usage.before_chars || 0).toLocaleString()} 字符 → 模型材料{" "}
          {(usage.after_chars || 0).toLocaleString()} 字符
        </p>
        <p>
          实际输入 / 输出 token：{usage.prompt_tokens || 0} /{" "}
          {usage.completion_tokens || 0}
        </p>
        <p>
          输入 token 保守估算：{usage.estimated_input_tokens || 0}（UTF-8
          字节上界，非计费量）
        </p>
      </div>
      <h4>检索记录</h4>
      {report.queries.map((query, index) => (
        <QueryEntry key={index} query={query} />
      ))}
    </>
  );
}
