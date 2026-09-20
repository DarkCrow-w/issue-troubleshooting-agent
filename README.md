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

2. 在 `.env` 中填写 PostgreSQL、Splunk、内部模型网关和内部服务令牌。

3. 修改 `config/settings.yaml`：

```yaml
environments:
  production:
    indexes: [company_application_index]
```

同时按实际日志调整 `correlation_fields`、服务别名、复合 ID 服务和成功业务码。

4. 构建并启动：

```bash
docker compose up -d --build
```

访问 <http://127.0.0.1:8080/>。PostgreSQL 中的 `tasks`、`evidence` 表和索引会在首次启动时自动创建。

如果 PostgreSQL 运行在 Docker 宿主机，macOS/Windows 可在 `DATABASE_URL` 中使用 `host.docker.internal`；Linux 应使用容器可访问的宿主机地址或把 PostgreSQL 放入同一 Docker network。

## 必需环境变量

| 变量 | 用途 |
| --- | --- |
| `SERVICE_TOKEN` | API 与 Agent 之间的内部认证 |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `SPLUNK_URL` | Splunk Management API 地址 |
| `SPLUNK_TOKEN` | Splunk Bearer token |
| `SPLUNK_VERIFY_TLS` | 是否验证 Splunk TLS 证书 |
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
