import {
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  FileInput,
  FileOutput,
  Logs,
  Settings2,
} from "lucide-react";
import type {
  JourneyNode,
  JourneyStatus,
  OpenEvidence,
  TransactionJourney as Journey,
} from "../../types";

const statusLabels: Record<JourneyStatus, string> = {
  success: "正常",
  failed: "发现错误",
  affected: "受错误影响",
  warning: "证据不完整",
  unknown: "待确认",
};

function StatusIcon({ status }: { status: JourneyStatus }) {
  if (status === "success") return <CheckCircle2 size={15} />;
  if (status === "failed" || status === "affected" || status === "warning") {
    return <CircleAlert size={15} />;
  }
  return <CircleDashed size={15} />;
}

function EvidenceActions({
  node,
  openEvidence,
}: {
  node: JourneyNode;
  openEvidence: OpenEvidence;
}) {
  const requestId = node.request_ids[0];
  const responseId = node.response_ids[0];
  const rawId = node.evidence_ids[0];
  return (
    <div className="journey-node-actions">
      {requestId && (
        <button onClick={() => openEvidence(requestId, "request")}>
          <FileInput size={13} /> Request
        </button>
      )}
      {responseId && (
        <button onClick={() => openEvidence(responseId, "response")}>
          <FileOutput size={13} /> Response
        </button>
      )}
      {rawId && (
        <button onClick={() => openEvidence(rawId, "raw")}>
          <Logs size={13} /> 原始证据
        </button>
      )}
    </div>
  );
}

const phaseMeta = {
  request: { icon: ArrowRight, focus: "request" as const },
  request_processing: { icon: Settings2, focus: "raw" as const },
  response: { icon: ArrowLeft, focus: "response" as const },
  response_processing: {
    icon: Settings2,
    focus: "raw" as const,
  },
};

function phaseLabel(phase: string, direction: string) {
  if (phase === "request") {
    if (direction === "inbound") return "请求接收";
    if (direction === "outbound") return "请求发送";
    return "请求";
  }
  if (phase === "request_processing") return "请求处理";
  if (phase === "response") {
    if (direction === "inbound") return "响应返回上游";
    if (direction === "outbound") return "响应接收";
    return "响应";
  }
  return "响应后处理";
}

function phaseStatusLabel(
  phase: string,
  status: JourneyStatus,
  direction: string,
) {
  if (phase === "response_processing" && status === "success") return "未见异常";
  if (status === "success" && phase === "request") {
    return direction === "inbound" ? "已接收" : "已发送";
  }
  if (status === "success" && phase === "request_processing") return "已完成";
  if (status === "success" && phase === "response") {
    return direction === "outbound" ? "已接收" : "已返回";
  }
  if (status === "failed") return "此处报错";
  if (status === "warning") return "证据不完整";
  return "未观测";
}

function CallPhases({
  node,
  openEvidence,
}: {
  node: JourneyNode;
  openEvidence: OpenEvidence;
}) {
  if (!node.phases) return null;
  return (
    <div className="call-phases" aria-label="调用生命周期">
      {Object.entries(phaseMeta).map(([phaseId, meta]) => {
        const phase = node.phases?.[phaseId as keyof typeof node.phases];
        if (!phase) return null;
        const evidenceId = phase.evidence_ids[0];
        const Icon = meta.icon;
        const content = (
          <>
            <span className="call-phase-name">
              <Icon size={13} /> {phaseLabel(phaseId, node.direction)}
            </span>
            <span className={`call-phase-status ${phase.status}`}>
              {phaseStatusLabel(phaseId, phase.status, node.direction)}
            </span>
          </>
        );
        return evidenceId ? (
          <button
            className={`call-phase ${phase.status}`}
            key={phaseId}
            onClick={() => openEvidence(evidenceId, meta.focus)}
          >
            {content}
          </button>
        ) : (
          <div className={`call-phase ${phase.status}`} key={phaseId}>
            {content}
          </div>
        );
      })}
    </div>
  );
}

function JourneyNodeCard({
  node,
  openEvidence,
  highlighted,
}: {
  node: JourneyNode;
  openEvidence: OpenEvidence;
  highlighted: boolean;
}) {
  return (
    <article
      className={`journey-node ${node.status} ${highlighted ? "highlighted" : ""}`}
    >
      <div className="journey-node-heading">
        <strong>{node.service || "服务未知"}</strong>
        <span className={`journey-status ${node.status}`}>
          <StatusIcon status={node.status} />
          {statusLabels[node.status]}
        </span>
      </div>
      <code>
        {node.method ? `${node.method} ` : ""}
        {node.api || "API 未识别"}
      </code>
      {node.failure_reasons.length > 0 && (
        <p>
          {node.failure_phase_label && `${node.failure_phase_label}：`}
          {node.failure_reasons.join("；")}
        </p>
      )}
      {node.missing_response && <p>已找到请求，暂未找到可配对响应</p>}
      {node.pairing_ambiguous && <p>请求/响应配对存在歧义</p>}
      {node.role === "unknown" && <p>服务角色待配置，暂列在 CM 区域</p>}
      <CallPhases node={node} openEvidence={openEvidence} />
      <EvidenceActions node={node} openEvidence={openEvidence} />
    </article>
  );
}

interface CmAppSummary {
  service: string;
  status: JourneyStatus;
  apiCount: number;
  callCount: number;
  reasons: string[];
  primaryNode: JourneyNode;
  isFaultApp: boolean;
}

// 聚合状态时优先展示最严重的结果，避免正常调用掩盖同一应用里的异常调用。
const statusPriority: Record<JourneyStatus, number> = {
  failed: 5,
  affected: 4,
  warning: 3,
  unknown: 2,
  success: 1,
};

function nodeRelevance(
  node: JourneyNode,
  attribution: Journey["attribution"],
) {
  const attributionEvidence = new Set(attribution.evidence_ids);
  let score = statusPriority[node.status];
  if (node.failure_reasons.length > 0) score += 20;
  if (node.direction === "outbound") score += 30;
  if (node.api) score += 20;
  if (node.evidence_ids.some((id) => attributionEvidence.has(id))) score += 500;
  if (node.id === attribution.node_id) score += 1000;
  return score;
}

function summarizeCmApps(
  nodes: JourneyNode[],
  attribution: Journey["attribution"],
): CmAppSummary[] {
  const apps = new Map<string, JourneyNode[]>();
  const attributionEvidence = new Set(attribution.evidence_ids);

  nodes.forEach((node) => {
    const service = node.service || "服务未知";
    const appNodes = apps.get(service) ?? [];
    appNodes.push(node);
    apps.set(service, appNodes);
  });

  return Array.from(apps, ([service, appNodes]) => {
    const status = appNodes.reduce<JourneyStatus>((current, node) => {
      return statusPriority[node.status] > statusPriority[current]
        ? node.status
        : current;
    }, "success");
    const apiCount = new Set(
      appNodes.map((node) => node.api).filter((api) => api && api !== "API 未识别"),
    ).size;
    const isFaultApp =
      attribution.domain === "cm" &&
      appNodes.some(
        (node) =>
          node.id === attribution.node_id ||
          node.evidence_ids.some((id) => attributionEvidence.has(id)),
      );

    // 根因节点的原因最重要，其次才采用同一应用中其他异常调用的原因。
    const orderedNodes = [...appNodes].sort((left, right) => {
      return nodeRelevance(right, attribution) - nodeRelevance(left, attribution);
    });
    const reasons = Array.from(
      new Set(
        orderedNodes.flatMap((node) => {
          const nodeReasons = [...node.failure_reasons];
          if (node.missing_response) nodeReasons.push("请求已发出，但没有找到对应响应");
          if (node.pairing_ambiguous) nodeReasons.push("请求与响应配对存在歧义");
          return nodeReasons;
        }),
      ),
    );
    const primaryNode =
      orderedNodes.find((node) => node.failure_reasons.length > 0) ?? orderedNodes[0];

    return {
      service,
      status,
      apiCount,
      callCount: appNodes.length,
      reasons,
      primaryNode,
      isFaultApp,
    };
  });
}

function CmAppCard({
  app,
  openEvidence,
}: {
  app: CmAppSummary;
  openEvidence: OpenEvidence;
}) {
  const hasError = app.status !== "success";
  const visibleReasons = app.reasons.slice(0, 2);
  const hiddenReasonCount = app.reasons.length - visibleReasons.length;

  return (
    <article
      className={`journey-app ${app.status} ${app.isFaultApp ? "highlighted" : ""}`}
    >
      <div className="journey-node-heading">
        <strong>{app.service}</strong>
        <span className={`journey-status ${app.status}`}>
          <StatusIcon status={app.status} />
          {app.isFaultApp ? "故障应用" : statusLabels[app.status]}
        </span>
      </div>
      <span className="journey-app-stats">
        {app.callCount} 个调用
        {app.apiCount > 0 && ` · ${app.apiCount} 个 API`}
      </span>
      {hasError && (
        <div className="journey-app-error">
          <strong>{app.isFaultApp ? "报错原因" : "异常信息"}</strong>
          <p>
            {visibleReasons.length > 0
              ? visibleReasons.join("；")
              : "日志标记了异常，但没有提取到明确原因"}
            {hiddenReasonCount > 0 && `；另有 ${hiddenReasonCount} 条`}
          </p>
        </div>
      )}
      <CallPhases node={app.primaryNode} openEvidence={openEvidence} />
      <EvidenceActions node={app.primaryNode} openEvidence={openEvidence} />
    </article>
  );
}

function EmptyStage() {
  return (
    <div className="journey-empty">
      <CircleDashed size={16} />
      当前日志没有识别到该区域的调用
    </div>
  );
}

function JourneyStageNodes({
  stage,
  attribution,
  openEvidence,
}: {
  stage: Journey["stages"][number];
  attribution: Journey["attribution"];
  openEvidence: OpenEvidence;
}) {
  if (stage.nodes.length === 0) return <EmptyStage />;

  if (stage.id === "cm") {
    const apps = summarizeCmApps(stage.nodes, attribution);
    return apps.map((app) => (
      <CmAppCard key={app.service} app={app} openEvidence={openEvidence} />
    ));
  }

  return stage.nodes.map((node) => (
    <JourneyNodeCard
      key={node.id}
      node={node}
      openEvidence={openEvidence}
      highlighted={node.id === attribution.node_id}
    />
  ));
}

type RouteId =
  | "upstream-request"
  | "downstream-request"
  | "downstream-response"
  | "upstream-response";

const routeStatusLabels: Record<JourneyStatus, string> = {
  success: "正常",
  failed: "故障",
  affected: "受影响",
  warning: "证据不足",
  unknown: "未观测",
};

const routeStatusPriority: Record<JourneyStatus, number> = {
  failed: 5,
  affected: 4,
  warning: 3,
  success: 2,
  unknown: 1,
};

function phaseStatus(
  nodes: JourneyNode[],
  phase: keyof NonNullable<JourneyNode["phases"]>,
): JourneyStatus {
  const statuses = nodes
    .map((node) => node.phases?.[phase].status)
    .filter((status): status is JourneyStatus => Boolean(status));
  if (!statuses.length) return "unknown";
  return statuses.reduce((current, status) =>
    routeStatusPriority[status] > routeStatusPriority[current]
      ? status
      : current,
  );
}

function faultRoute(journey: Journey): RouteId | undefined {
  const { domain, phase } = journey.attribution;
  if (domain === "upstream") return "upstream-request";
  if (domain !== "downstream") return undefined;
  return phase === "request" || phase === "request_processing"
    ? "downstream-request"
    : "downstream-response";
}

function routeStatuses(journey: Journey): Record<RouteId, JourneyStatus> {
  const upstream = journey.stages.find((stage) => stage.id === "upstream")?.nodes ?? [];
  const cm = journey.stages.find((stage) => stage.id === "cm")?.nodes ?? [];
  const downstream =
    journey.stages.find((stage) => stage.id === "downstream")?.nodes ?? [];
  const inboundCm = cm.filter((node) => node.direction === "inbound");
  const outboundCm = cm.filter((node) => node.direction === "outbound");
  const entryNodes = [...upstream, ...(inboundCm.length ? inboundCm : cm)];
  const downstreamCalls = outboundCm.length ? outboundCm : downstream;
  const raw: Record<RouteId, JourneyStatus> = {
    "upstream-request": phaseStatus(entryNodes, "request"),
    "downstream-request": phaseStatus(downstreamCalls, "request"),
    "downstream-response": phaseStatus(downstreamCalls, "response"),
    "upstream-response": phaseStatus(entryNodes, "response"),
  };
  const fault = faultRoute(journey);
  if (fault) raw[fault] = "failed";

  // 红色只表示确定的故障边；其他失败状态表示错误传播，避免多个“根因”。
  Object.keys(raw).forEach((id) => {
    const routeId = id as RouteId;
    if (raw[routeId] === "failed" && routeId !== fault) {
      raw[routeId] = "affected";
    }
  });
  return raw;
}

function stageName(stage: Journey["stages"][number]): string {
  const services = Array.from(
    new Set(
      stage.nodes
        .map((node) => node.service)
        .filter(
          (service) =>
            service &&
            service !== "上游系统" &&
            !service.startsWith("下游服务（"),
        ),
    ),
  );
  if (stage.id === "upstream") return services[0] ?? "上游系统";
  if (stage.id === "downstream") return services[0] ?? "下游系统";
  if (services.length === 1) return services[0];
  return services.length > 1 ? `CM（${services.length} 个应用）` : "CM";
}

function RouteConnector({
  status,
  label,
  direction,
}: {
  status: JourneyStatus;
  label: string;
  direction: "right" | "left";
}) {
  const Icon = direction === "right" ? ArrowRight : ArrowLeft;
  return (
    <div className={`route-connector ${direction} ${status}`} aria-label={`${label}：${routeStatusLabels[status]}`}>
      <span>{label}</span>
      <div>
        <i />
        <Icon size={18} />
      </div>
      <small>{routeStatusLabels[status]}</small>
    </div>
  );
}

function JourneyRoute({ journey }: { journey: Journey }) {
  const stages = Object.fromEntries(journey.stages.map((stage) => [stage.id, stage]));
  const names = {
    upstream: stageName(stages.upstream),
    cm: stageName(stages.cm),
    downstream: stageName(stages.downstream),
  };
  const statuses = routeStatuses(journey);
  return (
    <div className="journey-route-panel">
      <div className="journey-route-heading">
        <strong>完整请求与返回路径</strong>
        <span>箭头颜色表示每一段实际观测到的状态</span>
      </div>
      <div className="journey-route-scroll">
        <div className="journey-route-map">
          <span className="route-lane-label">请求</span>
          <div className="route-stop">{names.upstream}</div>
          <RouteConnector status={statuses["upstream-request"]} label="调用 CM" direction="right" />
          <div className="route-stop">{names.cm}</div>
          <RouteConnector status={statuses["downstream-request"]} label="调用下游" direction="right" />
          <div className="route-stop">{names.downstream}</div>

          <span className="route-lane-label response">返回</span>
          <div className="route-stop response">{names.upstream}</div>
          <RouteConnector status={statuses["upstream-response"]} label="返回上游" direction="left" />
          <div className="route-stop response">{names.cm}</div>
          <RouteConnector status={statuses["downstream-response"]} label="返回 CM" direction="left" />
          <div className="route-stop response">{names.downstream}</div>
        </div>
      </div>
    </div>
  );
}

function IssueConclusion({ attribution }: { attribution: Journey["attribution"] }) {
  const conclusion = attribution.conclusion ?? {
    title: attribution.label,
    detail: attribution.summary,
    owner: "待确认",
    action: "请结合完整日志继续排查。",
  };
  const healthy = attribution.domain === "none";
  return (
    <div className={`issue-conclusion ${attribution.domain}`}>
      <span className="issue-conclusion-label">
        {healthy ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
        明确结论
      </span>
      <div className="issue-conclusion-title">
        <h2>{conclusion.title}</h2>
        <span>建议处理方：{conclusion.owner}</span>
      </div>
      <p>{conclusion.detail}</p>
      <strong>{conclusion.action}</strong>
    </div>
  );
}

export default function TransactionJourney({
  journey,
  openEvidence,
}: {
  journey?: Journey;
  openEvidence: OpenEvidence;
}) {
  if (!journey?.stages.length) {
    return (
      <section className="journey-overview">
        <p className="muted">当前报告还没有生成标准化交易链路。</p>
      </section>
    );
  }

  const attribution = journey.attribution;
  const confidenceLabels: Record<string, string> = {
    high: "高",
    medium: "中",
    low: "低",
  };
  return (
    <section className="journey-overview">
      <IssueConclusion attribution={attribution} />
      <div className="journey-title">
        <div>
          <span className="eyebrow">TRANSACTION JOURNEY</span>
          <h3>交易链路定位</h3>
        </div>
        <span className={`fault-domain ${attribution.domain}`}>
          {attribution.label}
        </span>
      </div>
      <div className={`fault-summary ${attribution.domain}`}>
        <strong>证据定位：{attribution.summary}</strong>
        <span>
          归因可信度：{confidenceLabels[attribution.confidence] ?? "未知"} ·{" "}
          {attribution.caution}
        </span>
      </div>
      <JourneyRoute journey={journey} />
      <div className="journey-direction-legend">
        <span><ArrowRight size={14} /> 请求向下游发送</span>
        <span><ArrowLeft size={14} /> 响应向调用方返回</span>
        <span><Settings2 size={14} /> 返回后由当前服务继续处理</span>
      </div>
      <div className="journey-stages">
        {journey.stages.map((stage) => (
          <div className="journey-stage-wrap" key={stage.id}>
            <section className={`journey-stage ${stage.status}`}>
              <header>
                <div>
                  <strong>{stage.label}</strong>
                  <span>{stage.description}</span>
                </div>
                <span className={`journey-status ${stage.status}`}>
                  <StatusIcon status={stage.status} />
                  {statusLabels[stage.status]}
                </span>
              </header>
              <div className="journey-stage-nodes">
                <JourneyStageNodes
                  stage={stage}
                  attribution={attribution}
                  openEvidence={openEvidence}
                />
              </div>
            </section>
          </div>
        ))}
      </div>
    </section>
  );
}
