import argparse
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from ai_incident_investigator.knowledge.passage_labels import (
    ContextCase,
    ContextDataset,
    case_export_path,
)
from ai_incident_investigator.knowledge.recommendations import (
    MAX_EXPORT_BYTES,
    NO_ELIGIBLE_KNOWLEDGE_ISSUE,
    InvestigationExport,
    RecommendationArtifact,
)
from ai_incident_investigator.knowledge.vector_index import SearchRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "evals/knowledge-recommendations.json"
MODEL = "gpt-4.1-mini-2025-04-14"
SEARCH_LIMIT = 10
SETTINGS = {
    "model": MODEL,
    "limit": SEARCH_LIMIT,
    "max_characters": 2000,
    "context_max_chunks": 5,
    "context_max_bytes": 12000,
}


def read_inputs(dataset_path: Path) -> tuple[bytes, list[tuple[ContextCase, bytes]]]:
    dataset_bytes = dataset_path.read_bytes()
    dataset = ContextDataset.model_validate_json(dataset_bytes)
    inputs: list[tuple[ContextCase, bytes]] = []
    for case in dataset.cases:
        if "\x00" in case.query:
            raise ValueError(f"Query contains a null character for case {case.id}")
        with case_export_path(dataset_path, case).open("rb") as source:
            export_bytes = source.read(MAX_EXPORT_BYTES + 1)
        if len(export_bytes) > MAX_EXPORT_BYTES:
            raise ValueError(f"Investigation export is too large for case {case.id}")
        try:
            export = InvestigationExport.model_validate_json(export_bytes)
            SearchRequest(
                text=case.query,
                service=export.request.service,
                environment=export.request.environment,
                limit=SEARCH_LIMIT,
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid investigation export or search scope for {case.id}") from exc
        inputs.append((case, export_bytes))
    return dataset_bytes, inputs


def json_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def summarize_case(
    case: ContextCase,
    export_bytes: bytes,
    artifact_bytes: bytes,
    *,
    mode: str,
    exit_code: int,
) -> dict[str, object]:
    result: dict[str, object] = {
        "case_id": case.id,
        "expected_status": case.expected_status,
        "expected_issue": case.expected_issue,
        "exit_code": exit_code,
        "status": None,
        "technical_expectation_met": False,
    }
    if not artifact_bytes.strip():
        return {**result, "problem": "empty_artifact"}

    try:
        artifact = RecommendationArtifact.model_validate_json(artifact_bytes)
    except ValidationError:
        return {**result, "problem": "invalid_artifact"}

    if (
        artifact.query != case.query
        or artifact.input_sha256 != sha256(export_bytes).hexdigest()
        or artifact.mode != mode
        or artifact.model != MODEL
    ):
        return {**result, "problem": "artifact_mismatch"}

    no_scope_expected = (
        case.expected_status == "skipped" and case.expected_issue == NO_ELIGIBLE_KNOWLEDGE_ISSUE
    )
    expected_usage = not no_scope_expected or (
        artifact.collection is None and artifact.embedding_total_tokens == 0
    )
    passed = (
        exit_code == 0
        and artifact.status == case.expected_status
        and (artifact.status != "completed" or bool(artifact.collection))
        and (case.expected_issue is None or artifact.issue == case.expected_issue)
        and expected_usage
    )
    return {
        **result,
        "status": artifact.status,
        "issue": artifact.issue,
        "collection": artifact.collection,
        "embedding_total_tokens": artifact.embedding_total_tokens,
        "prompt_sha256": artifact.prompt_sha256,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "technical_expectation_met": passed,
        "problem": None if passed else "unexpected_outcome",
    }


def run_case(
    case: ContextCase,
    output: Path,
    export_path: Path,
    export_bytes: bytes,
    *,
    include_drafts: bool,
) -> dict[str, object]:
    case_dir = output / "cases" / case.id
    case_dir.mkdir(parents=True)
    artifact_path = case_dir / "recommendations.json"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/recommend_knowledge.py"),
        "--investigation",
        str(export_path),
        f"--query={case.query}",
    ]
    for key, value in SETTINGS.items():
        command.extend((f"--{key.replace('_', '-')}", str(value)))
    if include_drafts:
        command.append("--include-drafts")

    with artifact_path.open("wb") as stdout, (case_dir / "stderr.txt").open("wb") as stderr:
        process = subprocess.run(
            command, cwd=PROJECT_ROOT, stdout=stdout, stderr=stderr, check=False
        )
    (case_dir / "exit-code.txt").write_text(f"{process.returncode}\n", encoding="utf-8")

    return summarize_case(
        case,
        export_bytes,
        artifact_path.read_bytes(),
        mode="preview" if include_drafts else "approved",
        exit_code=process.returncode,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fixed knowledge recommendation cases.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True, help="New run directory.")
    parser.add_argument("--include-drafts", action="store_true")
    args = parser.parse_args()

    output = args.output.absolute()
    mode = "preview" if args.include_drafts else "approved"
    saved_dataset = output / "dataset.json"
    try:
        dataset_bytes, inputs = read_inputs(args.dataset)
        output.mkdir(parents=True)
        saved_dataset.write_bytes(dataset_bytes)
        for case, export_bytes in inputs:
            export_path = case_export_path(saved_dataset, case)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_bytes(export_bytes)
        (output / "run.json").write_text(
            json_text(
                {
                    "schema_version": 1,
                    "dataset_sha256": sha256(dataset_bytes).hexdigest(),
                    "mode": mode,
                    "settings": SETTINGS,
                    "case_ids": [case.id for case, _ in inputs],
                }
            ),
            encoding="utf-8",
        )
        results = [
            run_case(
                case,
                output,
                case_export_path(saved_dataset, case),
                export_bytes,
                include_drafts=args.include_drafts,
            )
            for case, export_bytes in inputs
        ]
        collections = sorted(
            {value for result in results if isinstance(value := result.get("collection"), str)}
        )
        prompts = sorted(
            {value for result in results if isinstance(value := result.get("prompt_sha256"), str)}
        )
        passed = (
            len(collections) <= 1
            and len(prompts) <= 1
            and all(result["technical_expectation_met"] for result in results)
        )
        summary = json_text(
            {
                "schema_version": 1,
                "collections": collections,
                "prompt_sha256s": prompts,
                "passed": passed,
                "cases": results,
            }
        )
        (output / "summary.json").write_text(summary, encoding="utf-8")
    except ValidationError:
        parser.exit(2, "Baseline failed: invalid dataset JSON.\n")
    except FileExistsError:
        parser.exit(2, "Baseline failed: output directory or file already exists.\n")
    except OSError:
        parser.exit(2, "Baseline failed: unable to read, write or start the recommendation CLI.\n")
    except ValueError as exc:
        parser.exit(2, f"Baseline failed: {exc}\n")

    print(summary, end="")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
