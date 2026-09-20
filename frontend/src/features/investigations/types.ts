export interface WorkflowConfig {
  workflows: { id: string; description: string; skills: string[] }[];
  environments: string[];
  source_mode: string;
  model_mode: string;
  model: string;
}
export interface Claim {
  statement: string;
  evidence_ids: string[];
  confidence: string;
  counter_evidence_ids?: string[];
  verification?: string;
}
export interface CallNode {
  id: string;
  service: string;
  api: string;
  evidence_ids: string[];
  missing_response?: boolean;
  pairing_ambiguous?: boolean;
  attempt?: string;
}
export interface Report {
  summary: string;
  graph: {
    nodes: CallNode[];
    edges: {
      source: string;
      target: string;
      certainty: string;
      reason: string;
      evidence_ids: string[];
    }[];
    services: string[];
    timeline: {
      event_id: string;
      timestamp: string;
      service: string;
      api: string;
      kind: string;
    }[];
  };
  findings: Claim[];
  hypotheses: Claim[];
  earliest_observed_failure: {
    event_id: string;
    service: string;
    timestamp: string;
    reasons: string[];
  } | null;
  unknowns: string[];
  next_steps: string[];
  warnings: string[];
  notes: string[];
  queries: {
    reason: string;
    count: number;
    spl: string;
    evidence_id: string;
  }[];
  markdown: string;
}
export interface Task {
  id: string;
  status: string;
  phase: string;
  usage: Record<string, number>;
  report: Report | null;
}

export interface InvestigationRequest {
  correlation_id: string;
  environment: string;
  workflow: string;
  start_time: string;
  end_time: string;
  cleaning_enabled: boolean;
  question: string;
}
