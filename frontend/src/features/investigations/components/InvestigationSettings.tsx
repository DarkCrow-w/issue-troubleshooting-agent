import { SlidersHorizontal } from "lucide-react";
import type { WorkflowConfig } from "../types";

export interface SearchSettings {
  environment: string;
  workflow: string;
  startTime: string;
  endTime: string;
  spl: string;
  cleaning: boolean;
  followup: boolean;
}

// 这里只负责编辑设置；请求转换与提交由外层表单负责。
export default function InvestigationSettings({
  config,
  value,
  onChange,
}: {
  config: WorkflowConfig | null;
  value: SearchSettings;
  onChange: (patch: Partial<SearchSettings>) => void;
}) {
  const { environment, workflow, startTime, endTime, spl, cleaning, followup } =
    value;
  return (
    <details className="settings">
      <summary>
        <SlidersHorizontal size={16} />
        排查设置<span>{environment}</span>
      </summary>
      <div className="settings-panel">
        <div className="settings-grid">
          <label>
            环境
            <select
              value={environment}
              onChange={(e) => onChange({ environment: e.target.value })}
            >
              {config?.environments.map((env) => (
                <option key={env}>{env}</option>
              ))}
            </select>
          </label>
          <label>
            排查流程
            <select
              value={workflow}
              onChange={(e) => onChange({ workflow: e.target.value })}
            >
              {config?.workflows.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.description}
                </option>
              ))}
            </select>
          </label>
          <label>
            开始时间 · UTC+08:00
            <input
              aria-label="开始时间"
              type="datetime-local"
              value={startTime}
              onChange={(e) => onChange({ startTime: e.target.value })}
            />
          </label>
          <label>
            结束时间 · UTC+08:00
            <input
              aria-label="结束时间"
              type="datetime-local"
              value={endTime}
              onChange={(e) => onChange({ endTime: e.target.value })}
            />
          </label>
        </div>
        <label className="spl-option">
          Splunk SPL · 可选
          <textarea
            aria-label="Splunk SPL"
            value={spl}
            onChange={(event) => onChange({ spl: event.target.value })}
            placeholder={'例如：search correlationId="..." | fields _time appName message'}
            rows={3}
          />
          <span>会自动限制到所选环境配置的 index；可与关联 ID 一起使用。</span>
        </label>
        <label className="cleaning-option">
          <input
            type="checkbox"
            checked={cleaning}
            onChange={(e) => onChange({ cleaning: e.target.checked })}
          />
          日志清洗<span>减少冗余，保留证据</span>
        </label>
        <label className="cleaning-option">
          <input
            type="checkbox"
            checked={followup}
            onChange={(e) => onChange({ followup: e.target.checked })}
          />
          自动补查<span>根据已有证据继续查询 Splunk，默认关闭</span>
        </label>
      </div>
    </details>
  );
}
