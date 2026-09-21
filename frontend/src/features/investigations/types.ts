export interface WorkflowConfig {
  workflows: { id: string; description: string; skills: string[] }[];
  environments: string[];
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
  direction?: string;
  evidence_ids: string[];
  missing_response?: boolean;
  pairing_ambiguous?: boolean;
  attempt?: string;
  request_ids?: string[];
  response_ids?: string[];
}
export type EvidenceFocus = "request" | "response" | "raw";
export type OpenEvidence = (id: string, focus?: EvidenceFocus) => void;
export type JourneyStatus =
  | "success"
  | "failed"
  | "affected"
  | "warning"
  | "unknown";
export interface JourneyPhase {
  status: JourneyStatus;
  evidence_ids: string[];
}
export interface JourneyNode {
  id: string;
  service: string;
  api: string;
  method: string;
  direction: string;
  peer_service: string;
  role: "upstream" | "cm" | "downstream" | "unknown";
  status: JourneyStatus;
  failure_reasons: string[];
  evidence_ids: string[];
  request_ids: string[];
  response_ids: string[];
  missing_response: boolean;
  pairing_ambiguous: boolean;
  virtual: boolean;
  failure_phase?: string;
  failure_phase_label?: string;
  phases?: {
    request: JourneyPhase;
    request_processing: JourneyPhase;
    response: JourneyPhase;
    response_processing: JourneyPhase;
  };
}
export interface TransactionJourney {
  stages: {
    id: "upstream" | "cm" | "downstream";
    label: string;
    description: string;
    status: JourneyStatus;
    nodes: JourneyNode[];
  }[];
  attribution: {
    domain: "upstream" | "cm" | "downstream" | "none" | "unknown";
    label: string;
    summary: string;
    confidence: string;
    node_id: string;
    evidence_ids: string[];
    caution: string;
    phase?: string;
    phase_label?: string;
  };
  caution: string;
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
  journey: TransactionJourney;
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
  spl: string;
  environment: string;
  workflow: string;
  start_time: string | null;
  end_time: string | null;
  cleaning_enabled: boolean;
  followup_enabled: boolean;
  question: string;
}
