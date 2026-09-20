import { useEffect, useState } from "react";
import { api } from "../../../shared/http";
import type { InvestigationRequest, Task, WorkflowConfig } from "../types";

const terminalStates = new Set(["completed", "partial", "failed", "cancelled"]);

export function useInvestigation() {
  const [config, setConfig] = useState<WorkflowConfig | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const busy =
    submitting || (!!taskId && (!task || !terminalStates.has(task.status)));

  useEffect(() => {
    api<WorkflowConfig>("/workflows")
      .then((value) => {
        setConfig(value);
      })
      .catch((error) => setError(error.message));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    // 切换任务或卸载后丢弃旧轮询响应；只更新页面，不输出重复轮询日志。
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api<Task>(`/investigations/${taskId}`);
        if (stopped) return;
        setTask(next);
        setError("");
        if (!terminalStates.has(next.status)) timer = setTimeout(poll, 1000);
      } catch (error) {
        if (stopped) return;
        setError((error as Error).message);
        timer = setTimeout(poll, 3000);
      }
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [taskId]);

  async function submit(request: InvestigationRequest) {
    setError("");
    setSubmitting(true);
    setTask(null);
    setTaskId(null);
    try {
      const next = await api<{ id: string }>("/investigations", {
        method: "POST",
        body: JSON.stringify(request),
      });
      setTaskId(next.id);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelTask() {
    try {
      await api(`/investigations/${taskId}/cancel`, { method: "POST" });
    } catch (error) {
      setError((error as Error).message);
    }
  }

  return { config, task, taskId, busy, error, submit, cancelTask };
}
