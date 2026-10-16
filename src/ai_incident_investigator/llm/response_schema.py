from collections.abc import Sequence
from copy import deepcopy
from typing import Annotated

from pydantic import AfterValidator, Field, create_model

from ai_incident_investigator.investigations.analysis import Analysis
from ai_incident_investigator.investigations.reports import (
    Finding,
    Hypothesis,
    Identifier,
)


def analysis_schema(evidence_ids: Sequence[str]) -> type[Analysis]:
    """Constrain model-generated references to this investigation's evidence IDs."""
    allowed_ids = tuple(evidence_ids)

    if not allowed_ids:
        raise ValueError("An analysis schema requires at least one evidence ID")

    known_ids = frozenset(allowed_ids)
    if len(known_ids) != len(allowed_ids):
        raise ValueError("Evidence IDs must be unique")

    def validate_reference(value: str) -> str:
        if value not in known_ids:
            raise ValueError("Reference must identify evidence supplied for this analysis")
        return value

    BoundIdentifier = Annotated[
        Identifier,
        Field(json_schema_extra={"enum": list(allowed_ids)}),
        AfterValidator(validate_reference),
    ]

    class BoundFinding(Finding):
        evidence_ids: list[BoundIdentifier] = Field(min_length=1)

    class BoundHypothesis(Hypothesis):
        supporting_evidence_ids: list[BoundIdentifier] = Field(min_length=1)
        contradicting_evidence_ids: list[BoundIdentifier] = Field(default_factory=list)

    return create_model(
        "EvidenceBoundAnalysis",
        __base__=Analysis,
        findings=(list[BoundFinding], deepcopy(Analysis.model_fields["findings"])),
        hypotheses=(
            list[BoundHypothesis],
            deepcopy(Analysis.model_fields["hypotheses"]),
        ),
    )
