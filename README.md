# IssueTroubleshooting

面向公司内网的交易日志问题定位系统。前端提交关联 ID 或 Splunk SPL；后端查询 Splunk、清洗大日志、还原服务调用链，并通过 LangGraph、可组合 skills 和内部大模型生成带原始证据引用的排查报告。

这个分支只保留生产运行需要的前后端代码和配置，不包含 Demo 日志、测试、截图、流程图或开发期迁移工具。系统固定使用 Splunk、PostgreSQL 和在线模型。

## 目录

```text
backend/troubleshooter/
  api/             浏览器 API 与内部 Agent API
  investigation/   LangGraph 流程、预算、补查与分块分析
  logs/            Splunk 查询、标准化和可选日志清洗
  models/          所有模型调用、LangChain adapter、prompt 与输出校验
  analysis/        请求响应、Java 异常、调用链和失败规则
  persistence/     PostgreSQL 任务与原始证据
  reports/         报告与 Markdown 输出
frontend/src/      React 极简排查页面
skills/            可组合的排查 skills
config/            环境、index、字段和 workflow 配置
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

4. 构建并启动：

```bash
docker compose up -d --build
```

访问 <http://127.0.0.1:8080/>。PostgreSQL 中的 `tasks`、`evidence` 表和索引会在首次启动时自动创建。

如果 PostgreSQL 运行在 Docker 宿主机，macOS/Windows 可在 `DATABASE_URL` 中使用 `host.docker.internal`；Linux 应使用容器可访问的宿主机地址或把 PostgreSQL 放入同一 Docker network。

## 不使用 Docker 本地启动

本地运行需要 Python 3.11 以上、Node.js 22 和一个可以连接的 PostgreSQL。所有命令都从项目根目录开始执行。

1. 首次安装后端依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -c backend/requirements.lock -e backend
```

如果公司网络不能访问公开软件源，请把 pip 和 npm 配置为公司的制品仓库后再安装。

2. 首次准备配置：

```bash
cp .env.example .env
chmod 600 .env
```

把 `.env` 中的 `DATABASE_URL`、`SPLUNK_CONNECTIONS` 和模型配置替换为公司环境的真实值，并同步修改 `config/settings.yaml` 中的环境和 index。已有 `.env` 时不要再次复制覆盖。

3. 在第一个终端启动 Agent Service：

```bash
source .venv/bin/activate
uvicorn troubleshooter.api.agent:create_app \
  --factory --app-dir backend --host 127.0.0.1 --port 8001
```

Agent Service 负责 Splunk 查询、LangGraph 排查流程、模型调用和 PostgreSQL 读写。

4. 在第二个终端启动浏览器 API：

```bash
source .venv/bin/activate
uvicorn troubleshooter.api.public:create_app \
  --factory --app-dir backend --host 127.0.0.1 --port 8000
```

本地模式下 `AGENT_URL` 默认是 `http://127.0.0.1:8001`，通常不需要额外配置。

5. 在第三个终端启动前端：

```bash
cd frontend
npm ci
npm run dev
```

浏览器访问 <http://127.0.0.1:5173/>。`npm ci` 只需在首次安装或依赖变化后运行，之后执行 `npm run dev` 即可。

可以用下面两个地址检查后端是否启动成功：

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
```

两个接口都返回 `status: ok` 后，再打开前端。停止系统时，在三个终端中分别按 `Ctrl+C`。

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
