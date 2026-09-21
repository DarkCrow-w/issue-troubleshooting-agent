# IssueTroubleshooting

面向公司内网的交易日志问题定位系统。前端提交关联 ID 或 Splunk SPL；后端查询 Splunk、清洗大日志、还原服务调用链，并通过 LangGraph、可组合 skills 和内部大模型生成带原始证据引用的排查报告。

这个分支只保留生产运行需要的前后端代码和配置，不包含 Demo 日志、测试、截图或流程图。系统固定使用 Splunk、PostgreSQL 和在线模型。

## 目录

```text
backend/troubleshooter/
  api/             浏览器 API 与内部 Agent API
  investigation/   LangGraph 流程、预算、补查与分块分析
  logs/            Splunk 查询、标准化和可选日志清洗
  models/          所有模型调用、LangChain adapter、prompt 与输出校验
  analysis/        请求响应、Java 异常、三段交易链路和故障域规则
  persistence/     PostgreSQL 任务与原始证据
  reports/         报告与 Markdown 输出
frontend/src/      React 极简排查页面
skills/            可组合的排查 skills
config/            环境、index、字段和 workflow 配置
alembic/           PostgreSQL 版本化迁移
```

## 内网接入

1. 复制环境变量模板：

```bash
cp .env.example .env
chmod 600 .env
```

2. 在 `.env` 中填写 PostgreSQL、各环境的 Splunk 连接、内部模型网关和内部服务令牌。`SPLUNK_CONNECTIONS` 是一行 JSON：

```dotenv
SPLUNK_CONNECTIONS='{"sit":{"url":"https://splunk-sit.company.internal:8089","token":"sit-token","verify_tls":true},"uat":{"url":"https://splunk-uat.company.internal:8089","token":"uat-token","verify_tls":true},"production":{"url":"https://splunk.company.internal:8089","token":"production-token","verify_tls":true}}'
```

每个环境可以使用不同的 URL、Token 和 TLS 设置。如果几个环境共用同一个 Splunk，只需重复填写相同 URL；各环境仍可配置不同 index。

3. 修改 `config/settings.yaml`：

```yaml
environments:
  sit:
    indexes: [company_sit_index]
  uat:
    indexes: [company_uat_index]
  production:
    indexes: [company_production_index]
```

`.env` 中的连接名称必须覆盖这里的所有环境名称。前端环境下拉框来自这里；后端收到查询后，会使用同名的 Splunk 连接和 index 白名单。请同时按实际日志调整 `correlation_fields`、服务别名、复合 ID 服务和成功业务码。

链路首屏固定按“上游 → CM 内部 → 下游”展示。请在 `config/settings.yaml` 的
`topology` 中补充公司服务命名规则，显式映射优先于正则：

```yaml
topology:
  service_roles:
    teller-channel: upstream
    core-banking: downstream
  cm_service_patterns: ['^cm-', '^comet-']
  upstream_service_patterns: ['^channel-']
  downstream_service_patterns: ['^core-', '^host-']
  # 日志缺少 peerService 时，可按稳定的下游 URL 前缀识别。
  downstream_api_patterns: ['^/core-banking/', '^/host-api/']
  # 只在入口根调用上匹配，用于识别上游参数或格式错误。
  upstream_input_error_patterns: ['(?i)validation|invalid parameter', '参数.*错误']
```

无法根据配置或明确调用边分类的服务会标为“服务角色待配置”，不会默认判定为
上游或下游。修改这些规则不需要改代码，也不会改变原始证据。

4. 构建并启动：

```bash
docker compose up -d --build
```

访问 <http://127.0.0.1:8080/>。Compose 会先运行一次 `alembic upgrade head`，成功创建或升级 PostgreSQL 表之后才启动 Agent。

如果 PostgreSQL 运行在 Docker 宿主机，macOS/Windows 可在 `DATABASE_URL` 中使用 `host.docker.internal`；Linux 应使用容器可访问的宿主机地址或把 PostgreSQL 放入同一 Docker network。

## 不使用 Docker 本地启动

本地运行需要 Python 3.11 以上、Node.js 22 和一个可以连接的 PostgreSQL。前后端依赖和运行命令全部由根目录的 `package.json` 管理，不使用额外启动脚本。

1. 首次安装全部依赖：

```bash
npm install
```

这条命令会在根目录安装前端依赖、创建 `.venv` 并安装锁定版本的 Python 依赖。如果公司网络不能访问公开软件源，请先把 pip 和 npm 配置为公司的制品仓库。

2. 首次复制配置，然后填写公司环境的真实值：

```bash
cp .env.example .env
chmod 600 .env
```

修改 `.env` 中的 `DATABASE_URL`、`SPLUNK_CONNECTIONS` 和模型配置，并同步修改 `config/settings.yaml` 中的环境和 index。`DATABASE_URL` 指向的数据库需要已经存在，表和索引由 Alembic 创建。

PostgreSQL 数据库是在 PostgreSQL 实例中创建的，不是在项目目录中创建。应用账号已经存在时，由管理员执行：

```bash
createdb \
  --host=数据库地址 \
  --port=5432 \
  --username=postgres \
  --owner=应用账号 \
  issue_troubleshooting
```

也可以登录 PostgreSQL 执行 SQL：

```sql
CREATE DATABASE issue_troubleshooting OWNER 应用账号;
```

如果应用账号也不存在，先由管理员创建账号：

```sql
CREATE ROLE issue_agent LOGIN PASSWORD '请替换为公司密钥';
CREATE DATABASE issue_troubleshooting OWNER issue_agent;
```

然后把 `.env` 配置为实际地址：

```dotenv
DATABASE_URL=postgresql://issue_agent:密码@数据库地址:5432/issue_troubleshooting
```

公司环境通常不允许应用账号执行 `CREATE DATABASE`。这种情况下把数据库名、Owner 和编码要求交给 DBA 创建即可；应用账号只需要能够连接该数据库并创建、读写自己的表。数据库创建完成后执行 `npm run db:init`。

3. 一条命令启动 Agent、浏览器 API 和前端：

```bash
npm run dev
```

该命令会先执行数据库初始化，再启动全部进程。浏览器访问 <http://127.0.0.1:5173/>。按一次 `Ctrl+C` 会同时停止三个进程。

需要分别开发或启停时，使用以下命令：

```bash
npm run dev:frontend  # 只启动前端 :5173
npm run dev:backend   # 启动 Agent :8001 和 Browser API :8000
npm run dev:agent     # 只启动 Agent
npm run dev:api       # 只启动 Browser API
```

`npm run dev:backend` 也会先初始化数据库。只启动 Agent 前，可以手动执行：

```bash
npm run db:init       # 升级到最新数据库版本，可重复执行
npm run db:status     # 查看当前数据库版本
```

日常只执行向前升级。`alembic downgrade` 会删除或改变数据库结构，执行前必须确认迁移内容并完成数据库备份。

前后端分开运行时，可以开两个终端：

```bash
# 终端一
npm run dev:backend

# 终端二
npm run dev:frontend
```

本地模式下 `AGENT_URL` 默认是 `http://127.0.0.1:8001`。前端开发服务器会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

可以用下面两个地址检查后端是否启动成功：

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
```

两个接口都返回 `status: ok` 后即可使用。

## 必需环境变量

| 变量 | 用途 |
| --- | --- |
| `SERVICE_TOKEN` | API 与 Agent 之间的内部认证 |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `SPLUNK_CONNECTIONS` | 各环境的 Splunk URL、Bearer token 和 TLS 设置，格式为 JSON 对象 |
| `LLM_BASE_URL` | 公司内部 OpenAI 兼容模型地址 |
| `LLM_API_KEY` | 模型访问密钥 |
| `LLM_MODEL` | 模型名称 |

运行预算、日志级别、数据保留时间和模型 token 上限在 `backend/troubleshooter/config/settings.py` 中有清晰默认值，需要时可在内网版本中统一修改。

## 修改内部模型调用

模型调用只存在于 `backend/troubleshooter/models/`：

- `calls.py` 提供 `propose_followups`、`analyze_evidence_chunk`、`analyze_expanded_evidence`、`synthesize_report` 四个业务方法。
- `client.py` 负责模型 SDK、认证、HTTP 兼容协议、结构化输出、有限修复、token usage 和错误转换。
- `prompts.py` 保存系统 prompt 模板。
- `validation.py` 校验模型引用的证据 ID。

公司内部模型调用方式变化时优先只修改 `client.py`；输入协议变化时再修改 `calls.py`。`investigation/` 中不应直接调用 LangChain 或模型 SDK。

## 查询接口

`POST /api/investigations` 示例：

```json
{
  "correlation_id": "交易关联ID",
  "spl": "",
  "environment": "production",
  "start_time": null,
  "end_time": null,
  "cleaning_enabled": true,
  "workflow": "standard",
  "question": "定位最早失败步骤和原因"
}
```

`correlation_id` 与 `spl` 至少填写一个。时间可以全部留空，也可以只设置一侧边界。自定义 SPL 会自动叠加所选环境允许的 index；系统拒绝子搜索、写入和跨源查询命令。

其他接口：

- `GET /api/investigations/{id}`：任务状态和报告
- `POST /api/investigations/{id}/cancel`：取消任务
- `GET /api/investigations/{id}/evidence/{eventId}`：读取 PostgreSQL 中的完整原始证据
- `GET /api/workflows`：环境、workflow 与模型信息

系统不进行数据脱敏。Splunk 日志、PostgreSQL 原始证据和关闭清洗时的模型材料均保留原值；部署与访问权限应遵循公司内部数据管理要求。
