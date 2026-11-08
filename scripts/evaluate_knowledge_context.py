import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_validator

from ai_incident_investigator.investigations.reports import ReportText
from ai_incident_investigator.knowledge.models import Identifier, KnowledgeModel
from ai_incident_investigator.knowledge.recommendations import RecommendationArtifact

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "evals/knowledge-recommendations.json"
Section = Annotated[str, Field(min_length=1, max_length=1000)]


class PassageLabel(KnowledgeModel):
    document_id: Identifier
    section: Section
    text_contains: ReportText | None = None


class ContextCase(KnowledgeModel):
    id: Identifier
    query: ReportText
    expected_status: Literal["completed", "skipped"]
    expected_issue: ReportText | None = None
    expected_context: tuple[PassageLabel, ...]
    review_questions: tuple[ReportText, ...]

    @field_validator("expected_context")
    @classmethod
    def validate_labels(cls, labels: tuple[PassageLabel, ...]) -> tuple[PassageLabel, ...]:
        keys = {
            (label.document_id, label.section, " ".join((label.text_contains or "").split()))
            for label in labels
        }
        if len(keys) != len(labels):
            raise ValueError("Expected passages must be unique")
        return labels


class ContextDataset(KnowledgeModel):
    schema_version: Literal[1]
    cases: tuple[ContextCase, ...] = Field(min_length=1)


def evaluate_context(case: ContextCase, artifact: RecommendationArtifact) -> dict[str, object]:
    assembly = artifact.assembly
    chunks = [hit.chunk for hit in assembly.context.chunks] if assembly is not None else []
    context_observed = artifact.status != "failed" or bool(chunks)
    passages = []
    matched = 0

    for label in case.expected_context:
        phrase = " ".join((label.text_contains or "").split())
        matches = [
            chunk.id
            for chunk in chunks
            if chunk.document.id == label.document_id
            and chunk.section == label.section
            and phrase in " ".join(chunk.content.split())
        ]
        matched += bool(matches)
        passages.append(
            {
                **label.model_dump(),
                "selected_chunk_ids": matches if context_observed else None,
            }
        )

    return {
        "case_id": case.id,
        "status": artifact.status,
        "issue": artifact.issue,
        "expected_status": case.expected_status,
        "expected_issue": case.expected_issue,
        "technical_expectation_met": artifact.status == case.expected_status
        and (case.expected_issue is None or artifact.issue == case.expected_issue),
        "passage_coverage": matched / len(passages) if context_observed and passages else None,
        "passages": passages,
        "omitted": [item.model_dump() for item in assembly.omitted] if assembly is not None else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate selected context in a saved artifact.")
    parser.add_argument("--case", required=True, help="Case ID in the baseline dataset.")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()

    try:
        dataset = ContextDataset.model_validate_json(args.dataset.read_bytes())
        cases = {case.id: case for case in dataset.cases}
        if len(cases) != len(dataset.cases):
            parser.exit(2, "Context evaluation failed: duplicate case IDs.\n")

        case = cases.get(args.case)
        if case is None:
            parser.exit(2, "Context evaluation failed: unknown case ID.\n")

        export = args.dataset.parent / "fixtures" / "knowledge-recommendations" / f"{case.id}.json"
        export_sha = sha256(export.read_bytes()).hexdigest()
        artifact_bytes = args.artifact.read_bytes()
        artifact = RecommendationArtifact.model_validate_json(artifact_bytes)
    except ValidationError:
        parser.exit(2, "Context evaluation failed: invalid dataset or artifact JSON.\n")
    except OSError:
        parser.exit(2, "Context evaluation failed: unable to read a file.\n")

    if artifact.query != case.query or artifact.input_sha256 != export_sha:
        parser.exit(
            2, "Context evaluation failed: artifact does not match the case export/query.\n"
        )

    result = evaluate_context(case, artifact)
    result["artifact_sha256"] = sha256(artifact_bytes).hexdigest()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
