import argparse
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from openai import OpenAI

from ai_incident_investigator.evaluation.dataset import load_dataset
from ai_incident_investigator.evaluation.live import (
    LiveEvaluationRun,
    run_live_evaluation,
)
from ai_incident_investigator.llm.openai_client import OpenAIAnalyzer

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def model_identifier(value: str) -> str:
    if not value.strip() or len(value) > 100:
        raise argparse.ArgumentTypeError("Model must contain 1 to 100 characters")
    return value.strip()


def save_checkpoint(output: Path, run: LiveEvaluationRun) -> None:
    temporary_path: Path | None = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(run.model_dump_json(indent=2) + "\n")

        os.replace(temporary_path, output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate LLM reports with recorded telemetry and explicit API opt-in."
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Allow billable requests to the official OpenAI API.",
    )
    parser.add_argument("--model", type=model_identifier, required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument(
        "--max-calls",
        type=int,
        choices=range(1, 11),
        default=3,
        help="Maximum analysis attempts; SDK retries are disabled.",
    )
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "evals" / "scenarios.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--revision", help="Optional commit identifier recorded as metadata.")
    args = parser.parse_args()

    if not args.allow_live:
        parser.error("Live API requests require the explicit --allow-live flag")

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        parser.error("Set OPENAI_API_KEY in the process environment before running evaluation")

    output = args.output or PROJECT_ROOT / "data" / "llm-evaluation" / f"{uuid4()}.json"

    try:
        dataset = load_dataset(args.dataset)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Reserve the destination before creating the API client; existing files are refused.
        with output.open("x", encoding="utf-8"):
            pass

        with OpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            timeout=20.0,
            max_retries=0,
        ) as client:
            result = run_live_evaluation(
                dataset,
                fixtures_dir=args.dataset.parent / "fixtures",
                analyzer=OpenAIAnalyzer(client, model=args.model),
                model=args.model,
                repeats=args.repeats,
                max_calls=args.max_calls,
                code_revision=args.revision,
                checkpoint=lambda run: save_checkpoint(output, run),
            )
    except (OSError, ValueError) as exc:
        # Exception messages may contain provider, filesystem, or environment details.
        raise SystemExit(f"Live evaluation failed: {type(exc).__name__}") from None

    for case in result.results:
        passed_checks = sum(check.passed for check in case.checks)
        print(
            f"{'PASS' if case.passed else 'FAIL'} {case.scenario_id} "
            f"repeat={case.repeat}; checks={passed_checks}/{len(case.checks)}; calls={case.calls}"
        )

    print(f"Analysis attempts: {result.total_calls}/{args.max_calls}; SDK retries disabled.")
    print("LLM semantic quality: pending manual review.")
    print(f"Results: {output}")

    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
