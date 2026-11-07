import json
import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/review_knowledge.py"
FIXTURE = ROOT / "tests/fixtures/knowledge/recommendations.json"


def invoke(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *arguments])
    runpy.run_path(str(SCRIPT), run_name="__main__")


def test_review_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "artifact.json"
    original = FIXTURE.read_bytes()
    artifact.write_bytes(original)
    review = tmp_path / "reviews/result.json"

    invoke(monkeypatch, "init", "--artifact", str(artifact), "--output", str(review))
    assert "not_reviewed" in capsys.readouterr().out

    check_args = ("check", "--artifact", str(artifact), "--review", str(review))
    with pytest.raises(SystemExit) as pending:
        invoke(monkeypatch, *check_args)
    assert pending.value.code == 1
    assert "pending_review" in capsys.readouterr().out

    data = json.loads(review.read_bytes())
    data.update(
        reviewer="fixture-reviewer",
        response_appropriateness="pass",
        limitations="pass",
        notes="The saved advice and limitations are appropriate for this fixture.",
    )
    for item in data["checks"]:
        item.update(
            knowledge_support="pass",
            evidence_relevance="pass",
            temporal_correctness="pass",
            actionability="pass",
            notes="The cited text supports this conditional historical check.",
        )
    review.write_text(json.dumps(data), encoding="utf-8")
    invoke(monkeypatch, *check_args)
    assert "reviewed_pass" in capsys.readouterr().out

    data["checks"][0]["knowledge_support"] = "fail"
    review.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit) as failed:
        invoke(monkeypatch, *check_args)
    assert failed.value.code == 1
    assert "reviewed_fail" in capsys.readouterr().out
    assert artifact.read_bytes() == original


@pytest.mark.parametrize("destination", ["source", "existing"])
def test_init_never_overwrites_files(
    destination: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(FIXTURE.read_bytes())
    output = artifact if destination == "source" else tmp_path / "existing.json"
    if destination == "existing":
        output.write_text("existing review", encoding="utf-8")
    original = output.read_bytes()

    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "init", "--artifact", str(artifact), "--output", str(output))
    assert error.value.code == 2
    assert "already exists" in capsys.readouterr().err.lower()
    assert output.read_bytes() == original


def test_invalid_data_does_not_leak_validation_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"private-marker":"DO_NOT_PRINT"}', encoding="utf-8")
    output = tmp_path / "review.json"

    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "init", "--artifact", str(artifact), "--output", str(output))
    assert error.value.code == 2
    assert not output.exists()
    assert "DO_NOT_PRINT" not in capsys.readouterr().err
