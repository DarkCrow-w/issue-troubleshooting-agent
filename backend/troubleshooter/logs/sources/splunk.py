"""通过当前排查环境对应的 Splunk 连接执行有界查询。"""

import asyncio
import json

import httpx

from troubleshooter.config.settings import Settings
from troubleshooter.domain.models import QuerySpec, SearchResult

from .query import build_spl


class SplunkSource:
    def __init__(self, settings: Settings, config: dict):
        self.settings = settings
        self.config = config

    async def search(self, query: QuerySpec, max_events: int, max_bytes: int) -> SearchResult:
        spl = build_spl(query, self.config)
        result = SearchResult(query=spl)
        connection = self.settings.splunk_connections[query.environment]
        headers = {"Authorization": "Bearer " + connection.token}
        async with httpx.AsyncClient(
            base_url=connection.url.rstrip("/"),
            headers=headers,
            verify=connection.verify_tls,
            timeout=30,
        ) as client:
            sid = ""
            try:
                search_data = {"search": spl, "output_mode": "json"}
                if query.start_time:
                    search_data["earliest_time"] = query.start_time.timestamp()
                if query.end_time:
                    search_data["latest_time"] = query.end_time.timestamp()
                response = await client.post(
                    "/services/search/jobs",
                    data=search_data,
                )
                response.raise_for_status()
                sid = response.json()["sid"]
                result.sid = sid
                for _ in range(120):
                    status = await client.get(
                        f"/services/search/jobs/{sid}", params={"output_mode": "json"}
                    )
                    status.raise_for_status()
                    content = status.json()["entry"][0]["content"]
                    if str(content.get("isFailed", "0")).lower() in ("1", "true"):
                        raise RuntimeError("Splunk 搜索任务失败")
                    if str(content.get("isDone", "0")).lower() in ("1", "true"):
                        break
                    await asyncio.sleep(0.5)
                else:
                    raise TimeoutError("Splunk 搜索等待超时")
                if str(content.get("eventIsTruncated", "0")).lower() in ("1", "true"):
                    result.warnings.append("Splunk 标记结果已截断")
                total = int(content.get("resultCount", 0))
                offset = 0
                while offset < total:
                    if len(result.records) >= max_events or result.bytes_read >= max_bytes:
                        result.warnings.append("日志预算已耗尽，结果不完整")
                        break
                    # Stream bounded pages so unexpectedly large bodies cannot exhaust memory.
                    page_bytes = bytearray()
                    async with client.stream(
                        "GET",
                        f"/services/search/jobs/{sid}/results",
                        params={
                            "output_mode": "json",
                            "offset": offset,
                            "count": min(200, max_events - len(result.records)),
                        },
                    ) as page:
                        page.raise_for_status()
                        async for chunk in page.aiter_bytes():
                            if result.bytes_read + len(page_bytes) + len(chunk) > max_bytes:
                                result.warnings.append("响应超过字节预算，当前页未读取")
                                result.bytes_read = max_bytes
                                return result
                            page_bytes.extend(chunk)
                    result.bytes_read += len(page_bytes)
                    entries = json.loads(page_bytes).get("results", [])
                    if not entries:
                        result.warnings.append("Splunk 分页提前结束，结果不完整")
                        break
                    result.records.extend(entries)
                    offset += len(entries)
            except (httpx.HTTPError, ValueError, KeyError, TimeoutError, RuntimeError) as exc:
                # Never expose remote response bodies or request headers in user-visible errors.
                status_code = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                result.warnings.append(
                    f"Splunk 查询失败：{type(exc).__name__}"
                    + (f"（HTTP {status_code}）" if status_code else "")
                )
            finally:
                if sid:
                    try:
                        await client.post(
                            f"/services/search/jobs/{sid}/control", data={"action": "cancel"}
                        )
                    except (httpx.HTTPError, asyncio.CancelledError):
                        pass
        return result
