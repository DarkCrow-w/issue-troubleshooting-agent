# 本地 Demo 交易

启动地址：<http://127.0.0.1:8080/>

所有案例使用相同条件：

- 环境：`demo`
- 开始时间：`2026-07-28 16:50`
- 结束时间：`2026-07-28 16:55`
- 建议开启“日志清洗”

| 交易 ID | 预期效果 |
|---|---|
| `demo-success-001` | 三个服务完整成功，无明确失败信号 |
| `demo-business-error-001` | HTTP 200，但账户服务返回 `LIMIT_EXCEEDED` |
| `demo-java-timeout-001` | Payment 服务出现 SQL 超时异常，上游随后返回 502 |
| `demo-retry-001` | 第一次调用 503，第二次重试成功，两个 attempt 独立展示 |
| `demo-multi-service-001` | 四服务调用链，Risk 服务返回 `RISK_REJECTED` |
| `demo-large-log-001` | 约 3 MB 单条日志，异常位于靠后位置，验证动态错误窗口 |

重新生成回放文件：

```bash
.venv/bin/python scripts/generate_demo_logs.py
```
