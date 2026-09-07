import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.learning.redaction import MAX_EVENT_BYTES, redact_data
from app.modules.learning.schemas import EventCreate


def test_event_schema_rejects_unknown_events_and_naive_dates() -> None:
    data = dict(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        execution_id=uuid4(),
        execution_kind="agent_run",
        source="agents",
        idempotency_key="test",
        event_type="user.message",
        occurred_at=datetime.now(UTC),
    )
    assert EventCreate(**data).event_type == "user.message"
    with pytest.raises(ValidationError):
        EventCreate(**{**data, "event_type": "agent.chain_of_thought"})
    with pytest.raises(ValidationError):
        EventCreate(**{**data, "occurred_at": datetime(2026, 9, 7)})
    with pytest.raises(ValidationError):
        EventCreate(**{**data, "scratchpad": "private reasoning"})


def test_redacts_credentials_nested_fields_and_classified_paths() -> None:
    result = redact_data(
        {
            "apiKey": "key-value",
            "credentials": {"username": "secret-user"},
            "nested": {"password": "hidden", "safe": "count=4", "privateKey": "private"},
            "note": "Bearer abcdefg https://user:pass@example.com/api password=hunter2",
            "private": "-----BEGIN PRIVATE KEY-----\nkey-data\n-----END PRIVATE KEY-----",
            "customer": {"email": "private@example.com"},
            "items": [{"value": "classified"}],
        },
        ["customer.email", "items.0.value"],
    )
    encoded = json.dumps(result)
    for secret in (
        "key-value",
        "secret-user",
        "hunter2",
        "key-data",
        "abcdefg",
        "user:pass",
        "private@example.com",
        "classified",
    ):
        assert secret not in encoded
    assert result["nested"]["safe"] == "count=4"


def test_hidden_reasoning_is_excluded_but_explicit_decision_is_allowed() -> None:
    result = redact_data(
        {
            "reasoning": "private",
            "chain_of_thought": "private",
            "scratchpad": "private",
            "nested": {"reasoningSummary": "private", "analysis": "private"},
            "decision": "inspect failing job",
            "reason": "job reported a failure",
        }
    )
    assert "private" not in json.dumps(result)
    assert result["reason"] == "job reported a failure"


def test_metadata_has_depth_count_and_byte_budgets() -> None:
    assert len(redact_data({"items": list(range(100))})["items"]) == 32
    large = redact_data({str(i): "x" * 4000 for i in range(64)})
    assert large["payload_omitted"]
    assert len(json.dumps(large).encode()) < MAX_EVENT_BYTES
