import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../shared/http";

export interface EvidenceView {
  id: string;
  data?: unknown;
  error?: string;
}

export function useEvidence(taskId: string | null) {
  const [evidence, setEvidence] = useState<EvidenceView | null>(null);
  const evidenceRequest = useRef(0);
  const closeEvidence = useCallback(() => {
    // 关闭时使在途请求失效，防止迟到的响应重新打开抽屉。
    evidenceRequest.current++;
    setEvidence(null);
  }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeEvidence();
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [closeEvidence]);

  async function openEvidence(id: string) {
    // 用户快速切换证据时，只接受最后一次点击对应的响应。
    const request = ++evidenceRequest.current;
    setEvidence({ id });
    try {
      const data = await api(`/investigations/${taskId}/evidence/${id}`);
      if (request === evidenceRequest.current) setEvidence({ id, data });
    } catch (error) {
      if (request === evidenceRequest.current)
        setEvidence({ id, error: (error as Error).message });
    }
  }

  return { evidence, openEvidence, closeEvidence };
}
