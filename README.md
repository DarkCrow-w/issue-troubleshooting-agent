# IssueTroubleshooting · 交易问题排查 Agent

通过交易关联 ID 从 Splunk 查询日志，还原服务/API 调用，定位失败步骤，输出带证据的诊断。前端使用 React，API Service 和 Agent Service 是两个独立 Python 进程。

**开箱即用的是离线演示。** 不需要公司网络或模型密钥即可验证整个界面。切换 live 模式后使用真实 Splunk / OpenAI 兼容模型。截图中的公司数据未写入项目，`examples/transaction.json` 全部是合成日志。

## 本地运行

需要 Python 3.11+、Node.js 22+ 和 PostgreSQL。先按下方“数据库配置”配置 `.env`。

```bash
./scripts/dev.sh
```

脚本会按锁定版本安装/更新 Python 依赖（首次创建 `.venv`），安装前端依赖，然后启动：

- React：<http://127.0.0.1:5173>
- API Service：<http://127.0.0.1:8000/docs>
- Agent Service：<http://127.0.0.1:8001/docs>（业务接口需要服务令牌）

页面预填演示 ID `demo-java-timeout-001`、环境 `demo` 和 UTC+08:00 时间 `2026-07-28 16:50–16:55`。直接点击“开始排查”即可看到 Java 异常、下游超时和上游 502 的传播过程。

Docker 默认加载包含六笔交易的 `examples/demo-pack.json`。可直接使用成功、业务失败、Java 超时、重试、四服务链路和 3 MB 大日志案例，完整 ID 与预期结果见 [Demo 清单](examples/DEMO.md)。

原有的单交易 `examples/transaction.json` 和 `examples/success.json` 仍可单独配置为 `REPLAY_PATH`。

离线模式输出确定性事实和未知信息，不冒充模型根因分析。网页可查看调用实例、明确/推测调用边、时间线、原始日志，导出 Markdown/JSON。数据默认保留 24 小时，定时清理；Agent 重启时将未完成任务标记为中断。

## 数据库配置

本项目使用 **PostgreSQL**，原始日志仍在 Splunk。当前本机连接的是 Homebrew PostgreSQL 17（`127.0.0.1:5432`），专用数据库和账号均为 `tracelens`，密码保存在本机 `.env`。

新环境先创建专用角色和数据库，再参考 `.env.example` 配置：

```dotenv
DATABASE_URL=postgresql://tracelens:your-password@127.0.0.1:5432/tracelens
DOCKER_DATABASE_URL=postgresql://tracelens:your-password@host.docker.internal:5432/tracelens
```

`DATABASE_URL` 用于本机 Python 服务；`DOCKER_DATABASE_URL` 用于 Docker Desktop 中的 Agent，两者应连接同一个数据库。Linux/公司部署应替换成容器实际可达的数据库地址。Compose 不会创建 PostgreSQL 容器，也不管理本机数据库的启动和备份。

首次启动自动创建 `tasks` 与 `evidence` 表。任务时间使用 `TIMESTAMPTZ`，报告和原始证据使用 `JSONB`；证据外键关联任务，过期删除在同一事务中级联清理。默认仍保留 24 小时，只运行一个 Agent worker。

旧 SQLite 数据可先停止旧 Agent、使用 SQLite backup API 创建一致性备份，然后导入：

```bash
.venv/bin/python -m troubleshooter.persistence.migrate_sqlite /absolute/path/backup.db
```

导入保留原任务 ID、时间和内容，在一个事务内完成；重复运行不覆盖已有数据。迁移前备份必须包含 WAL 中已提交的数据，不能只复制运行中的 `.db` 文件。本机迁移备份保存在 `data/backups/`，旧 Docker 数据卷保留作回退来源，应用不再向 SQLite 写入。备份不受应用 24 小时自动清理策略管理，应按公司数据保留要求另行清理。

测试连接真实 PostgreSQL，为每个测试创建并删除独立 schema；不会清理业务 schema。可用 `TEST_DATABASE_URL` 指定专用测试库，未设置时读取 `.env` 的 `DATABASE_URL`，测试账号需要 CREATE SCHEMA 权限。

## 接入公司环境

复制 `.env.example` 为 `.env`，仅在本机填入真实凭据，建议 `chmod 600 .env`。`.env` 已被 Git 和 Docker 忽略。

```dotenv
SOURCE_MODE=live
MODEL_MODE=live
SERVICE_TOKEN=replace-with-a-long-random-value
SPLUNK_URL=https://your-splunk-host:8089
SPLUNK_TOKEN=your-token
SPLUNK_VERIFY_TLS=true
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=your-key
LLM_MODEL=qwen3.8-flash
```

模型也可配置为 `deepseek-v4-flash-0731` 或 `kimi-k3`，以该账户实际可用模型为准。没有将用户提供的密钥保存到任何项目文件。本次重构后已用 qwen3.8-flash 对合成交易完成 LangChain + LangGraph 全流程真实接口验证，验证范围见 [验证记录](VALIDATION.md)。

在 `config/settings.yaml` 添加环境和允许访问的 index。按项目配置关联字段、复合 seqNo 拆分适用服务、服务别名和业务成功码。重启 Agent 后生效；进行中的任务使用启动时加载的配置与 prompt，并记录版本/摘要和配置快照。

可以分别设置数据源和模型：`SOURCE_MODE=replay` + `MODEL_MODE=live` 可先对合成或本地样本验证模型，不需要连公司 Splunk。`REPLAY_PATH` 支持 Splunk JSON 数组、`{"results": [...]}` 和逐行 JSON，忽略 preview 结果。

原生 Splunk 使用 `/services/search/jobs` 提交搜索，等待最终结果后分页读取 `/results`。认证使用 Bearer token。开启 live 数据源前必须修改默认内部服务令牌。API Service 应置于公司 SSO/访问控制后；本地默认只监听 loopback。首版不提供多租户隔离或账户系统，不应直接作为公网服务。

## 代码结构与数据流

```text
React
  └─ API Service：HTTP 接口、状态/结果转发
       └─ Agent Service：队列、任务状态、取消、证据库
            └─ 查询 → 标准化 → 保存原始证据 → 确定性 skills
                 → 有预算的补查 → 模型 skills → 证据校验 → 报告
```

```text
backend/troubleshooter/
  bootstrap.py     组装配置、数据源、存储与排查服务
  api/             public.py 网页 API；agent.py 内部 API
  investigation/   LangGraph 流程、任务调度、预算、补查、分块分析
  models/          LangChain 模型适配、提示词模板、输出引用校验
  logs/            标准化、可选清洗；sources/ 内含 Splunk 与回放
  analysis/        请求响应、Java 异常、调用链、失败信号规则
  skills/          manifest、注册表、依赖校验、可信处理器执行
  domain/          公共输入、日志事件、模型输出与错误类型
  reports/         报告组装与 Markdown 渲染
  persistence/     PostgreSQL 任务及 JSONB 原始证据
  config/          环境变量设置
frontend/src/
  app/             页面布局与样式
  features/investigations/
    components/    表单、报告、调用图、证据抽屉
    hooks/         任务提交/轮询/取消、证据读取
    types.ts       前后端数据契约
  shared/          通用 HTTP 客户端
skills/            可组合的提示词与 manifest
config/            环境、字段与 workflow 配置
examples/          合成日志
```

LangGraph 的 `StateGraph` 明确控制查询、代码 skills、补查循环、分块分析及报告节点。LangChain 负责统一模型调用、提示词模板和 Pydantic 输出解析。沿用独立的业务函数与数据类型，规则提取事实，模型综合解释；模型不能直接执行 SPL、访问任意网络或运行 shell。

使用少量直接解决问题的设计：数据源/模型适配器、可信 skill 策略注册表、构造函数依赖注入，以及显式状态图。没有增加通用插件容器或多层继承。入口与阅读顺序见 [架构与扩展说明](docs/architecture.md)。Python 使用 Ruff，前端使用 Prettier 格式化。

## 定制 skill 和 prompt

每个目录包含 `skill.yaml` 和 `prompt.md`。这些是本产品的 skill 插件，不依赖某个 IDE 的技能系统。

内置流程：

| Skill | 实现 | 作用 |
| --- | --- | --- |
| request-response | code | 提取和配对调用实例，标记缺失/歧义 |
| exception-analysis | code | Java 异常、Caused by、栈证据 |
| trace-reconstruction | code | 服务/API、父子调用、时间线 |
| failure-localization | code | HTTP、业务码、异常失败信号 |
| evidence-followup | followup | 提出并验证补查请求 |
| diagnosis-report | report | 模型综合或离线事实报告 |

增加一个业务分析 skill，例如 `skills/business-error/skill.yaml`：

```yaml
id: business-error
version: '1.0.0'
description: 解释账户服务业务错误码
kind: llm
depends_on: [failure-localization]
tools: [read_evidence]
input: events-and-artifacts
output: evidence-claims
```

对应 `prompt.md` 可以包含团队维护的错误码知识：

```text
分析账户业务错误码。ACCT_TIMEOUT 表示账户服务报告查询超时，
不能据此断言数据库宕机。区分证据和假设，所有结论引用事件 ID。
输出 JSON：
{"summary":"...","findings":[{"statement":"...","evidence_ids":["ev_..."],"confidence":"high"}],
 "hypotheses":[],"unknowns":[],"next_steps":[],"evidence_requests":[]}
```

将它加入 workflow，放在 `diagnosis-report` 前，同时把它加入 `diagnosis-report` 的 `depends_on`，确保最终报告消费该分析。`confidence` 只能是 `high/medium/low`。`hypotheses` 与 finding 结构相同，可增加 `counter_evidence_ids` 和 `verification`。模型可以通过 `evidence_requests` 请求最多三条已有证据的完整原始内容，仅允许 manifest 声明了 `read_evidence` 的 skill 执行，单个分块最多展开一轮，仍受 token 和调用预算约束。

各 LLM skill 接收当前证据分块和前序 skill 产物的有界摘要。多块报告会在预算允许时综合；未分析/未综合部分会明确列为限制。code skill 的 `prompt.md` 是职责说明，修改规则需要修改可信处理器；不会因为修改自然语言就改变确定性解析。新增代码处理器需在 `analysis.HANDLERS` 注册，再从 manifest 引用，重启后加载；不执行动态上传代码。

`workflows` 定义不同组合；网页可切换 workflow。依赖缺失、循环、重复 skill、不允许的工具以及不支持的 LLM 输出契约会在启动时失败。

## 清洗、证据与不确定性

- 关联 ID 是字符串，不限定 UUID。保留完整 `seqNo`，仅对配置的服务拆出 `root:businessSequence`。不将所有 ID 字段强行视为等价。
- 已提取字段与 `_raw` 冲突时保留完整原文，标明冲突并优先提取字段。无法解析的 Java Map 混合文本不会被丢弃。
- 清洗关闭时，完整原始记录直接进入模型材料；模型输入仍受预算限制，超长记录分片，不静默截断。
- 清洗开启时，每个超长字段默认最多保留约 16,000 字符：头部 3,000、尾部 4,000，以及最多 6 个分布在全文中的异常、超时、HTTP/业务错误码上下文窗口；Java 堆栈最多保留 80 行并优先留下异常链。重复正文共享内容引用，每次调用保留时间、实例、ID 和次数。小日志加上标准化结构后可能比原文更长，页面展示实际前后字符数而不虚报压缩率。
- 明确调用 ID 配对请求响应；显式 parentCallId/parentSpanId 建立明确边。目标服务与关联 ID 只能产生推测边。缺失 span/callId 时不靠时间编造链路。
- 同实例的邻近日志标为 `context`；未证明归属的上下文不会进入交易调用图。它们只能为模型提供线索。
- 最早观测到的错误不是根因；时钟偏差、采样、日志丢失、重试和业务错误码配置都会影响判断。
- 模型输出验证结构和引用 ID 的存在，不能机械证明每句话的语义正确。根因需人工结合证据验证。
- 本系统不进行数据脱敏。PostgreSQL、前端证据和关闭清洗时的模型材料均保留原始字段和值；清洗开启时只压缩冗余和超长内容。

默认预算：首次查询 + 3 次补查，10,000 条检索结果、50 MB 响应、8 次模型调用、180 秒执行期限。上下文补查为同实例前后 2 秒，且不超出用户时间范围。分页重复返回也占用检索预算，报告另列唯一事件数。每次输入按 UTF-8 字节上界估算 token，默认限 16,000；`LLM_MAX_OUTPUT_TOKENS` 默认 8,192，为模型推理和最终回答预留输出空间，必须小于 `LLM_CONTEXT_TOKENS`。实际计费 token 来自模型 usage。额度不足、模型故障、取消或超时保留已完成事实，展示部分结果。

## 接口

公共 API：

- `POST /api/investigations`：异步提交，返回 `202 {id,status}`。
- `GET /api/investigations/{id}`：状态、阶段、usage、快照和报告。
- `POST /api/investigations/{id}/cancel`：取消排队或执行中的任务。
- `GET /api/investigations/{id}/evidence/{eventId}`：原始证据。
- `GET /api/workflows`：环境、workflow 和运行模式。

提交示例：

```json
{
  "correlation_id": "demo-java-timeout-001",
  "spl": "",
  "environment": "demo",
  "start_time": "2026-07-28T16:50:00+08:00",
  "end_time": "2026-07-28T16:55:00+08:00",
  "cleaning_enabled": true,
  "workflow": "standard",
  "question": "请定位失败步骤，区分传播错误与根因假设"
}
```

`correlation_id` 与 `spl` 至少填写一个。`start_time`、`end_time` 都可以传 `null`；只填写一个时表示单侧时间边界。自定义 SPL 会与所选环境的 index 限制、关联 ID 条件组合，例如：

```json
{
  "correlation_id": "",
  "spl": "search correlationId=\"交易ID\" | fields _time appName message stacktrace",
  "environment": "prod",
  "start_time": null,
  "end_time": null,
  "cleaning_enabled": true,
  "workflow": "standard",
  "question": "定位最早失败步骤"
}
```

内部接口路径使用 `/internal` 替代 `/api`，要求 `Authorization: Bearer <SERVICE_TOKEN>`。任务状态：`queued/running/completed/partial/failed/cancelled`。一次部署运行一个 Agent worker，顺序处理任务，避免多 worker 重复恢复同一数据库中的任务。

## 排查应用自身的问题

关键业务日志统一为单行 JSON，默认 `LOG_LEVEL=INFO`。每条包含 `timestamp`、`level`、`event`、`task_id`；具体事件另带耗时、条数、调用次数或安全的错误位置。

```bash
# 实时查看 Agent 的排查过程
docker compose logs -f --no-log-prefix agent

# 按任务 ID 过滤（完整 ID 在提交接口响应和导出的 JSON 中）
docker compose logs --no-log-prefix agent | rg '你的任务ID'
```

常用事件：

| 事件 | 含义 |
| --- | --- |
| `task.queued / started / finished` | 排队、开始、最终状态和总耗时 |
| `query.started / completed` | 日志查询开始、返回条数、字节数及处理耗时 |
| `model.requested / responded` | 模型调用次数、输入/输出 token 及耗时 |
| `model.output_rejected / output_truncated` | 输出结构或引用无效、输出被截断 |
| `model.budget_exhausted` | 输入或调用预算不足 |
| `skill.failed / task.execution_failed` | 执行失败，带错误类型和代码行号 |
| `task.cancel_requested / cancelled / timeout` | 取消请求、已停止、达到期限 |
| `retention.deleted / failed / recovered` | 实际删除、首次清理故障、恢复 |

需要查看图节点顺序时，在 `.env` 设置 `LOG_LEVEL=DEBUG`，重启 Agent 后会增加 `graph.node_completed`。不建议长期保留 DEBUG。健康检查、状态轮询和逐条日志解析不输出成功访问流水；后台清理没有删除数据时不记日志，持续故障只记首次及恢复。

应用运行日志不输出交易关联 ID、请求正文、SPL、prompt、模型回答、连接串或密钥。异常只保留类型和最近的代码位置，不输出业务正文或局部变量。完整业务证据通过页面的原始证据入口查看。容器启动信息由 Uvicorn/Nginx 自身输出，不属于业务 JSON 事件。

## 测试与部署

```bash
.venv/bin/ruff check backend
(cd backend && ../.venv/bin/pytest -q)
npm run build --prefix frontend

# 在 ./scripts/dev.sh 已运行、且使用离线演示模式时：
cd frontend
npx playwright install chromium
npx playwright test
```

容器部署：

```bash
docker compose up --build
```

入口 <http://127.0.0.1:8080>，Agent/API 仅在容器网络暴露。公司部署时替换 `.env`、配置文件和外层访问控制，保留 TLS 校验。不要把公司生产密钥写入构建参数或镜像。

已使用 mock HTTP 验证 Splunk 协议、分页失败和查询限制；**本环境没有公司 Splunk 的地址、凭据和完整样本，因此真实 Splunk 联调尚未完成**。内网验收应使用一笔成功交易、业务失败交易、下游异常交易及重试/并发样本，核对人工已知链路和证据，再调整服务字段与业务码配置。
