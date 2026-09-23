from types import SimpleNamespace

from troubleshooter.domain.models import Event, InvestigationRequest
from troubleshooter.investigation.budget import RunBudget
from troubleshooter.investigation.packing import prepare_chunks

CLEANING_CONFIG = {
    "body_max_chars": 16_000,
    "head_chars": 3_000,
    "tail_chars": 4_000,
    "signal_window_chars": 1_500,
    "max_signal_windows": 6,
    "selected_field_max_chars": 2_000,
    "stack_max_frames": 80,
    "keep_body_fields": [],
}


def _settings():
    return SimpleNamespace(
        max_input_tokens=120_000,
        llm_context_tokens=128_000,
        llm_max_output_tokens=8_000,
        max_events=10_000,
        max_bytes=50_000_000,
        max_followups=3,
        max_model_calls=8,
    )


def _events() -> list[Event]:
    repeated_ids = {f"key_{index}": "x" * 24 for index in range(20)}
    return [
        Event(
            id=f"ev_{index:03}",
            timestamp=f"2026-09-23T10:00:{index % 60:02}.000+08:00",
            service="cm-demo",
            instance="cm-demo-pod",
            ids=repeated_ids,
            correlation_ids=["corr-demo"],
            level="DEBUG",
            message="routine processing message",
            source={
                "index": "demo-index",
                "source": "container" * 10,
                "sourcetype": "kube:container",
                "_bkt": "bucket" * 10,
                "_cd": str(index),
            },
        )
        for index in range(136)
    ]


def test_repeated_metadata_does_not_create_extra_model_calls():
    events = _events()
    state = {
        "events": {event.id: event for event in events},
        "records": {event.id: {"_raw": event.message} for event in events},
        "artifacts": {},
    }
    request = InvestigationRequest(
        correlation_id="corr-demo",
        environment="sit",
    )
    budget = RunBudget(_settings())

    chunks = prepare_chunks(
        state,
        request,
        {"cleaning": CLEANING_CONFIG},
        budget,
    )

    assert len(chunks) == 1
    assert all("source" not in item for item in chunks[0])
    assert chunks[0][1]["ids"] == {
        "same_content_as": chunks[0][0]["id"],
        "field": "ids",
    }
