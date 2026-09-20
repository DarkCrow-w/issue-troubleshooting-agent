"""Splunk and local replay implement the same bounded search interface."""

from typing import Protocol

from troubleshooter.domain.models import QuerySpec, SearchResult


class LogSource(Protocol):
    async def search(self, query: QuerySpec, max_events: int, max_bytes: int) -> SearchResult: ...
