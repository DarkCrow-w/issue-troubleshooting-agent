"""Deterministic facts: these remain available even if a model is unavailable."""

from datetime import datetime

from troubleshooter.domain.models import Event


def time_key(event: Event):
    try:
        return datetime.fromisoformat(event.timestamp).timestamp(), event.id
    except ValueError:
        return float("inf"), event.id
