import argparse
from pathlib import Path

from ai_incident_investigator.evaluation.review import (
    ReviewStatus,
    RunReview,
    create_review,
    evaluate_review,
    load_run,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record and check a manual review of saved LLM evaluation outputs."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="Create an unreviewed template.")
    initialize.add_argument("--run", type=Path, required=True)
    initialize.add_argument("--output", type=Path, required=True)

    check = commands.add_parser("check", help="Validate and summarize an existing review.")
    check.add_argument("--run", type=Path, required=True)
    check.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()

    try:
        run, source_sha256 = load_run(args.run)

        if args.command == "init":
            if args.output.resolve() == args.run.resolve():
                raise ValueError("The review must not overwrite its source run")

            review = create_review(run, source_sha256=source_sha256)
            args.output.parent.mkdir(parents=True, exist_ok=True)

            with args.output.open("x", encoding="utf-8") as output:
                output.write(review.model_dump_json(indent=2) + "\n")

            print(f"Review template created: model={run.model}; cases={len(review.cases)}.")
            print("All decisions remain not_reviewed. Fill in the reviewer and case assessments.")
            return

        review = RunReview.model_validate_json(args.review.read_bytes())
        status = evaluate_review(run, review, source_sha256=source_sha256)
    except (OSError, ValueError) as exc:
        # Validation errors may contain excerpts from private investigation data.
        parser.exit(2, f"Review failed: {type(exc).__name__}\n")

    print(f"Review status: {status.value}; model={run.model}; cases={len(review.cases)}.")
    print("This result applies only to the saved outputs and the recorded manual assessments.")

    if status != ReviewStatus.PASSED:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
