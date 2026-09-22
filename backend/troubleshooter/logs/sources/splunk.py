"""通过当前排查环境对应的 Splunk 连接执行有界查询。"""

import asyncio
import json

import httpx

from troubleshooter.config.settings import Settings
from troubleshooter.domain.models import QuerySpec, SearchResult

from .query import build_spl

POLL_INTERVAL_SECONDS = 0.5
MAX_POLL_ATTEMPTS = 120
PAGE_SIZE = 200


def _is_true(value) -> bool:
    return str(value).lower() in ("1", "true")


class SplunkSource:
    """Splunk Adapter；调用方只需要知道有界 ``search`` interface。"""

    def __init__(self, settings: Settings, config: dict):
        self.settings = settings
        self.config = config

    async def _create_job(
        self, client: httpx.AsyncClient, query: QuerySpec, spl: str
    ) -> str:
        data = {"search": spl, "output_mode": "json"}
        if query.start_time:
            data["earliest_time"] = query.start_time.timestamp()
        if query.end_time:
            data["latest_time"] = query.end_time.timestamp()
        response = await client.post("/services/search/jobs", data=data)
        response.raise_for_status()
        return response.json()["sid"]

    async def _wait_for_job(self, client: httpx.AsyncClient, sid: str) -> dict:
        for _ in range(MAX_POLL_ATTEMPTS):
            response = await client.get(
                f"/services/search/jobs/{sid}", params={"output_mode": "json"}
            )
            response.raise_for_status()
            content = response.json()["entry"][0]["content"]
            if _is_true(content.get("isFailed", "0")):
                raise RuntimeError("Splunk 搜索任务失败")
            if _is_true(content.get("isDone", "0")):
                return content
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        raise TimeoutError("Splunk 搜索等待超时")

    async def _read_page(
        self,
        client: httpx.AsyncClient,
        sid: str,
        offset: int,
        count: int,
        result: SearchResult,
        max_bytes: int,
    ) -> list[dict] | None:
        page_bytes = bytearray()
        async with client.stream(
            "GET",
            f"/services/search/jobs/{sid}/results",
            params={"output_mode": "json", "offset": offset, "count": count},
        ) as page:
            page.raise_for_status()
            async for chunk in page.aiter_bytes():
                if result.bytes_read + len(page_bytes) + len(chunk) > max_bytes:
                    result.warnings.append("响应超过字节预算，当前页未读取")
                    result.bytes_read = max_bytes
                    return None
                page_bytes.extend(chunk)
        result.bytes_read += len(page_bytes)
        return json.loads(page_bytes).get("results", [])

    async def _read_results(
        self,
        client: httpx.AsyncClient,
        sid: str,
        total: int,
        result: SearchResult,
        max_events: int,
        max_bytes: int,
    ) -> None:
        offset = 0
        while offset < total:
            if len(result.records) >= max_events or result.bytes_read >= max_bytes:
                result.warnings.append("日志预算已耗尽，结果不完整")
                return
            count = min(PAGE_SIZE, max_events - len(result.records))
            entries = await self._read_page(
                client, sid, offset, count, result, max_bytes
            )
            if entries is None:
                return
            if not entries:
                result.warnings.append("Splunk 分页提前结束，结果不完整")
                return
            result.records.extend(entries)
            offset += len(entries)

    async def _cancel_job(self, client: httpx.AsyncClient, sid: str) -> None:
        if not sid:
            return
        try:
            await client.post(
                f"/services/search/jobs/{sid}/control", data={"action": "cancel"}
            )
        except (httpx.HTTPError, asyncio.CancelledError):
            pass

    @staticmethod
    def _record_failure(result: SearchResult, error: Exception) -> None:
        # 远端响应正文和请求头可能含敏感信息，只暴露异常类型与状态码。
        status_code = (
            error.response.status_code
            if isinstance(error, httpx.HTTPStatusError)
            else None
        )
        status = f"（HTTP {status_code}）" if status_code else ""
        result.warnings.append(f"Splunk 查询失败：{type(error).__name__}{status}")

    async def search(
        self, query: QuerySpec, max_events: int, max_bytes: int
    ) -> SearchResult:
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
                sid = await self._create_job(client, query, spl)
                result.sid = sid
                content = await self._wait_for_job(client, sid)
                if _is_true(content.get("eventIsTruncated", "0")):
                    result.warnings.append("Splunk 标记结果已截断")
                total = int(content.get("resultCount", 0))
                await self._read_results(
                    client, sid, total, result, max_events, max_bytes
                )
            except (
                httpx.HTTPError,
                ValueError,
                KeyError,
                TimeoutError,
                RuntimeError,
            ) as error:
                self._record_failure(result, error)
            finally:
                await self._cancel_job(client, sid)
        return result
