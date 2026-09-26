from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_incident_investigator.investigations.schemas import InvestigationRequest


@pytest.fixture
def valid_payload() -> dict[str, object]:
    return {
        "service": "order-service",
        "environment": "local",
        "start_time": "2026-09-19T10:00:00Z",
        "end_time": "2026-09-19T10:10:00Z",
    }


def test_valid_request(valid_payload: dict[str, object]) -> None:
    request = InvestigationRequest.model_validate(valid_payload)

    assert request.service == "order-service"
    assert request.environment == "local"
    assert request.start_time == datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    assert request.end_time == datetime(2026, 9, 19, 10, 10, tzinfo=UTC)
    assert request.description is None


def test_strings_are_trimmed(valid_payload: dict[str, object]) -> None:
    valid_payload.update(
        service=" order-service ",
        environment=" local ",
        description=" Users cannot create orders. ",
    )

    request = InvestigationRequest.model_validate(valid_payload)

    assert request.service == "order-service"
    assert request.environment == "local"
    assert request.description == "Users cannot create orders."


def test_timestamps_are_normalized_to_utc(valid_payload: dict[str, object]) -> None:
    valid_payload["start_time"] = "2026-09-19T13:00:00+03:00"

    request = InvestigationRequest.model_validate(valid_payload)

    assert request.start_time == datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    assert request.start_time.tzinfo == UTC


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("service", "  ", "string_too_short"),
        ("environment", "", "string_too_short"),
        ("service", "a" * 101, "string_too_long"),
        ("environment", "a" * 101, "string_too_long"),
        ("service", 123, "string_type"),
        ("start_time", "2026-09-19T10:00:00", "timezone_aware"),
        ("end_time", "2026-09-19T10:10:00", "timezone_aware"),
        ("description", "a" * 4001, "string_too_long"),
        ("unexpected", "value", "extra_forbidden"),
    ],
)
def test_invalid_fields_are_rejected(
    valid_payload: dict[str, object],
    field: str,
    value: object,
    error_type: str,
) -> None:
    valid_payload[field] = value

    with pytest.raises(ValidationError) as exc_info:
        InvestigationRequest.model_validate(valid_payload)

    assert any(
        error["loc"] == (field,) and error["type"] == error_type
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize("field", ["service", "environment", "start_time", "end_time"])
def test_required_fields_cannot_be_omited(valid_payload: dict[str, object], field: str) -> None:
    del valid_payload[field]

    with pytest.raises(ValidationError) as exc_info:
        InvestigationRequest.model_validate(valid_payload)

    assert any(
        error["loc"] == (field,) and error["type"] == "missing" for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    "end_time",
    [
        "2026-09-19T09:59:00Z",
        "2026-09-19T10:00:00Z",
        "2026-09-19T13:00:00+03:00",
    ],
)
def test_end_must_be_after_start(valid_payload: dict[str, object], end_time: str) -> None:
    valid_payload["end_time"] = end_time

    with pytest.raises(ValidationError, match="end_time must be later than start_time"):
        InvestigationRequest.model_validate(valid_payload)


@pytest.mark.parametrize("field", ["start_time", "end_time"])
@pytest.mark.parametrize("value", [1789812000, "1789812000", "not-a-date"])
def test_unsupported_timestamp_inputs_are_rejected(
    valid_payload: dict[str, object],
    field: str,
    value: object,
) -> None:
    valid_payload[field] = value

    with pytest.raises(ValidationError) as exc_info:
        InvestigationRequest.model_validate(valid_payload)

    assert any(error["loc"] == (field,) for error in exc_info.value.errors())


@pytest.mark.parametrize("field", ["start_time", "end_time"])
def test_naive_datetime_objects_are_rejected(
    valid_payload: dict[str, object],
    field: str,
) -> None:
    valid_payload[field] = datetime(2026, 9, 19, 10, 0)

    with pytest.raises(ValidationError) as exc_info:
        InvestigationRequest.model_validate(valid_payload)

    assert any(
        error["loc"] == (field,) and error["type"] == "timezone_aware"
        for error in exc_info.value.errors()
    )


def test_maximum_string_lengths_are_accepted(
    valid_payload: dict[str, object],
) -> None:
    valid_payload.update(
        service="a" * 100,
        environment="b" * 100,
        description="c" * 4000,
    )

    request = InvestigationRequest.model_validate(valid_payload)

    assert request.service == "a" * 100
    assert request.environment == "b" * 100
    assert request.description == "c" * 4000


def test_explicit_null_description_is_accepted(
    valid_payload: dict[str, object],
) -> None:
    valid_payload["description"] = None

    request = InvestigationRequest.model_validate(valid_payload)

    assert request.description is None


def test_json_round_trip(valid_payload: dict[str, object]) -> None:
    request = InvestigationRequest.model_validate(valid_payload)

    restored = InvestigationRequest.model_validate_json(request.model_dump_json())

    assert restored == request
