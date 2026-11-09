import json
import sys
from pathlib import Path

import pytest

from scripts import compare_knowledge_chunking as cli

EVALS = Path(__file__).resolve().parents[1] / "evals"
PASSAGE = "Compare retained payment logs against the configured failure mode and incident timestamp"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "payment-timeout.md").write_text(
        f"# Release checks\n\n{PASSAGE}.\n", encoding="utf-8"
    )
    (knowledge / "catalog.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "include_runbooks": False,
                "documents": [
                    {
                        "id": "payment-timeout",
                        "title": "Release checks",
                        "document_type": "runbook",
                        "service": "order-service",
                        "environment": "local",
                        "owner": "fixture-owner",
                        "version": 1,
                        "status": "approved",
                        "reviewed_by": "fixture-reviewer",
                        "file": "knowledge/payment-timeout.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    case_ids = ("simulated-payment-timeout", "no-eligible-scope")
    dataset = json.loads((EVALS / "knowledge-recommendations.json").read_bytes())
    cases_by_id = {case["id"]: case for case in dataset["cases"]}
    cases = [cases_by_id[case_id] for case_id in case_ids]
    cases[0]["expected_context"] = [
        {
            "document_id": "payment-timeout",
            "section": "Release checks",
            "text_contains": PASSAGE,
        }
    ]
    fixtures = Path("fixtures/knowledge-recommendations")
    evals = tmp_path / "evals"
    (evals / fixtures).mkdir(parents=True)
    for case_id in case_ids:
        export = fixtures / f"{case_id}.json"
        (evals / export).write_bytes((EVALS / export).read_bytes())
    (evals / "knowledge-recommendations.json").write_text(
        json.dumps({"schema_version": 1, "cases": cases}), encoding="utf-8"
    )
    return tmp_path


@pytest.mark.parametrize(
    ("candidate_limit", "expected_changed", "expected_coverage"),
    [(512, [], 1.0), (64, ["payment-timeout"], 0.0)],
    ids=["identical-layout", "split-passage"],
)
def test_compares_layout_and_passage_coverage(
    corpus: Path,
    candidate_limit: int,
    expected_changed: list[str],
    expected_coverage: float,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare_knowledge_chunking.py",
            "--root",
            str(corpus),
            "--candidate-max-characters",
            str(candidate_limit),
        ],
    )
    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "approved"
    assert result["reference"] == {"max_characters": 2000, "chunk_count": 1}
    assert result["candidate"]["max_characters"] == candidate_limit
    assert result["changed_document_ids"] == expected_changed
    labeled, unlabeled = result["cases"]
    assert labeled["case_id"] == "simulated-payment-timeout"
    assert (labeled["service"], labeled["environment"]) == ("order-service", "local")
    assert labeled["reference_passage_coverage"] == 1.0
    assert labeled["candidate_passage_coverage"] == expected_coverage
    (passage,) = labeled["passages"]
    assert passage["text_contains"] == PASSAGE
    assert len(passage["reference_chunk_ids"]) == 1
    if expected_changed:
        assert result["candidate"]["chunk_count"] > 1
        assert passage["candidate_chunk_ids"] == []
    else:
        assert result["candidate"]["chunk_count"] == 1
        assert len(passage["candidate_chunk_ids"]) == 1
        assert passage["candidate_chunk_ids"] != passage["reference_chunk_ids"]
    assert unlabeled["case_id"] == "no-eligible-scope"
    assert unlabeled["reference_passage_coverage"] is None
    assert unlabeled["candidate_passage_coverage"] is None
    assert unlabeled["passages"] == []
