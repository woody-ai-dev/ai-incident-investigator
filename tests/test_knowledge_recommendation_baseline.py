import json
from pathlib import Path

import pytest

from ai_incident_investigator.knowledge.recommendations import InvestigationExport

EVALS = Path(__file__).resolve().parents[1] / "evals"
MANIFEST = EVALS / "knowledge-recommendations.json"
EXPORTS = EVALS / "fixtures" / "knowledge-recommendations"
CASE_IDS: list[str] = [
    case["id"] for case in json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_baseline_export_matches_cli_contract(case_id: str) -> None:
    InvestigationExport.model_validate_json((EXPORTS / f"{case_id}.json").read_bytes())