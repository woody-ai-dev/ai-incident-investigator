from pathlib import Path

import pytest

from ai_incident_investigator.knowledge.applicability import applicable_hits
from ai_incident_investigator.knowledge.documents import KnowledgeMetadata
from ai_incident_investigator.knowledge.extraction import LocalDocumentExtractor
from ai_incident_investigator.knowledge.loader import load_corpus
from ai_incident_investigator.knowledge.passage_labels import (
    ContextCase,
    ContextDataset,
    case_export_path,
    matching_chunk_ids,
)
from ai_incident_investigator.knowledge.recommendations import InvestigationExport
from ai_incident_investigator.knowledge.retrieval_chunks import prepare_document_chunks
from ai_incident_investigator.knowledge.retrieval_context import assemble_context
from ai_incident_investigator.knowledge.vector_index import SearchHit, SearchRequest
from ai_incident_investigator.llm.knowledge_recommender import (
    HISTORICAL_CHECK_CONDITION,
    instruction_choices,
    recommendation_schema,
    render_recommendations,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "evals" / "knowledge-recommendations.json"
DATASET = ContextDataset.model_validate_json(MANIFEST.read_bytes())


def load_export(case: ContextCase) -> InvestigationExport:
    return InvestigationExport.model_validate_json(case_export_path(MANIFEST, case).read_bytes())


@pytest.mark.parametrize("case", DATASET.cases, ids=lambda case: case.id)
def test_baseline_export_matches_cli_contract(case: ContextCase) -> None:
    load_export(case)


def test_scrape_case_admits_labeled_partial_collection_passage() -> None:
    case = next(case for case in DATASET.cases if case.id == "scrape-and-late-health")
    label = next(
        label for label in case.expected_context if label.document_id == "partial-collection"
    )
    runbook = next(
        item
        for item in load_corpus(PROJECT_ROOT / "runbooks")
        if item.metadata.id == label.document_id
    )
    metadata = KnowledgeMetadata.model_validate(
        {
            **runbook.metadata.model_dump(),
            "document_type": "runbook",
            "file": f"runbooks/{runbook.metadata.file}",
        }
    )
    document = LocalDocumentExtractor().extract(metadata, runbook.content.encode("utf-8"))
    chunks = prepare_document_chunks(document)
    labeled_ids = set(matching_chunk_ids(label, chunks))
    hits = tuple(SearchHit(chunk=chunk, score=1.0) for chunk in chunks if chunk.id in labeled_ids)

    assert hits, "The labeled partial-collection passage must exist in the prepared runbook"
    investigation = load_export(case)
    assert applicable_hits(investigation, hits) == hits

    report_without_outcomes = investigation.report.model_copy(update={"source_collections": None})
    export_without_outcomes = investigation.model_copy(update={"report": report_without_outcomes})
    assert applicable_hits(export_without_outcomes, hits) == ()

    context = assemble_context(
        SearchRequest(
            text=case.query,
            service=investigation.request.service,
            environment=investigation.request.environment,
        ),
        hits,
        include_drafts=True,
    ).context
    choices = instruction_choices(context, investigation.report.source_collections)
    (partial_check,) = choices
    assert partial_check.text.startswith("For partial coverage,")
    assert partial_check.knowledge_id in labeled_ids
    assert instruction_choices(context, None) == ()

    plan = recommendation_schema(
        [item.id for item in investigation.report.evidence], choices
    ).model_validate(
        {
            "checks": [
                {
                    "instruction_index": 0,
                    "reason": "Recorded metric collection is partial.",
                    "evidence_ids": [],
                }
            ],
            "limitations": [],
        }
    )
    (check,) = render_recommendations(plan, choices).checks
    assert check.action == HISTORICAL_CHECK_CONDITION + partial_check.text
    assert check.knowledge_ids == (partial_check.knowledge_id,)
    assert check.evidence_ids == ()
