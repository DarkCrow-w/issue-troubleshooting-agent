"""Deterministic facts: these remain available even if a model is unavailable."""

from troubleshooter.domain.models import Event


def exception_analysis(events: list[Event], config: dict, artifacts: dict) -> dict:
    return {
        "exceptions": [
            {
                "event_id": e.id,
                "service": e.service,
                "type": e.exception["type"],
                "message": e.exception["message"],
                "causes": e.exception["causes"],
            }
            for e in events
            if e.exception
        ]
    }
