import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_incident_investigator.evaluation.knowledge_review import create_review, evaluate_review
from ai_incident_investigator.evaluation.review import ReviewStatus
from ai_incident_investigator.knowledge.recommendations import RecommendationArtifact
from ai_incident_investigator.knowledge.retrieval_context import ContextAssembly

FIXTURE = Path(__file__).parent / "fixtures/knowledge/recommendations.json"
CHECK_CRITERIA = (
    "knowledge_support",
    "evidence_relevance",
    "temporal_correctness",
    "actionability",
)
GLOBAL_CRITERIA = ("response_appropriateness", "limitations")


@pytest.fixture
def source_json() -> bytes:
    return FIXTURE.read_bytes()


def approved_data(source_json: bytes) -> dict[str, Any]:
    data = create_review(source_json).model_dump(mode="json")
    data["reviewer"] = "Fixture reviewer"
    data["notes"] = "The checks apply to the incident and preserve its limitations."
    for criterion in GLOBAL_CRITERIA:
        data[criterion] = "pass"
    for check in data["checks"]:
        check["notes"] = "The cited guidance supports a conditional check of retained records."
        for criterion in CHECK_CRITERIA:
            check[criterion] = "pass"
    return data


def test_template_is_pending_and_bound_to_the_source(source_json: bytes) -> None:
    review = create_review(source_json)

    assert review.source_sha256 == sha256(source_json).hexdigest()
    assert [check.check_index for check in review.checks] == [0, 1]
    assert evaluate_review(source_json, review.model_dump_json().encode()) == ReviewStatus.PENDING


@pytest.mark.parametrize("criterion", (*CHECK_CRITERIA, *GLOBAL_CRITERIA))
def test_each_criterion_can_fail_review(source_json: bytes, criterion: str) -> None:
    data = approved_data(source_json)
    target = data["checks"][0] if criterion in CHECK_CRITERIA else data
    target[criterion] = "fail"

    assert evaluate_review(source_json, json.dumps(data).encode()) == ReviewStatus.FAILED


def test_a_failure_takes_precedence_over_pending_assessments(source_json: bytes) -> None:
    data = approved_data(source_json)
    data["checks"][0]["knowledge_support"] = "fail"
    data["checks"][1]["actionability"] = "not_reviewed"

    assert evaluate_review(source_json, json.dumps(data).encode()) == ReviewStatus.FAILED


@pytest.mark.parametrize(
    ("row", "field", "value"),
    [
        (None, "reviewer", "  "),
        (None, "notes", "  "),
        (0, "notes", "  "),
        (0, "check_index", False),
    ],
    ids=["blank-reviewer", "blank-global-notes", "blank-check-notes", "boolean-index"],
)
def test_invalid_assessments_are_rejected(
    source_json: bytes, row: int | None, field: str, value: str | bool
) -> None:
    data = approved_data(source_json)
    target = data if row is None else data["checks"][row]
    target[field] = value

    with pytest.raises(ValidationError):
        evaluate_review(source_json, json.dumps(data).encode())


@pytest.mark.parametrize(
    "indexes", [(0,), (0, 2), (0, 0)], ids=["missing", "wrong-index", "duplicate"]
)
def test_review_must_cover_exactly_the_saved_checks(
    source_json: bytes, indexes: tuple[int, ...]
) -> None:
    data = approved_data(source_json)
    data["checks"] = [dict(data["checks"][0], check_index=index) for index in indexes]

    with pytest.raises(ValueError, match="exactly match"):
        evaluate_review(source_json, json.dumps(data).encode())


def test_review_is_bound_to_exact_source_bytes(source_json: bytes) -> None:
    review_json = json.dumps(approved_data(source_json)).encode()

    with pytest.raises(ValueError, match="different source"):
        evaluate_review(source_json + b"\n", review_json)


@pytest.mark.parametrize("status", ["skipped", "failed"])
def test_noncompleted_artifacts_have_no_semantic_review(source_json: bytes, status: str) -> None:
    artifact = RecommendationArtifact.model_validate_json(source_json)
    data = artifact.model_dump(mode="json")
    data.update(status=status, recommendations=None, issue="Fixture has no completed answer.")
    if status == "skipped":
        assert artifact.assembly is not None
        context = artifact.assembly.context.model_copy(update={"chunks": ()})
        data["assembly"] = ContextAssembly(
            context=context,
            policy=artifact.assembly.policy,
            payload_bytes=context.payload_bytes,
        ).model_dump(mode="json")
        data["generation_usage"] = None
    incomplete = RecommendationArtifact.model_validate(data).model_dump_json().encode()

    with pytest.raises(ValueError, match="completed"):
        create_review(incomplete)
    with pytest.raises(ValueError, match="completed"):
        evaluate_review(incomplete, create_review(source_json).model_dump_json().encode())


def test_empty_recommendations_need_explicit_global_review(source_json: bytes) -> None:
    data = json.loads(source_json)
    data["recommendations"] = {
        "checks": [],
        "limitations": ["The selected guidance is insufficient for a useful check."],
    }
    abstention = json.dumps(data).encode()
    review = create_review(abstention)

    assert review.checks == []
    assert evaluate_review(abstention, review.model_dump_json().encode()) == ReviewStatus.PENDING

    approved = approved_data(abstention)
    assert evaluate_review(abstention, json.dumps(approved).encode()) == ReviewStatus.PASSED
    approved["limitations"] = "not_reviewed"
    assert evaluate_review(abstention, json.dumps(approved).encode()) == ReviewStatus.PENDING
