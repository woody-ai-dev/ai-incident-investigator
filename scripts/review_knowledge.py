import argparse
from pathlib import Path

from pydantic import ValidationError

from ai_incident_investigator.evaluation.knowledge_review import (
    create_review,
    evaluate_review,
)
from ai_incident_investigator.evaluation.review import ReviewStatus


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record a manual review of saved knowledge recommendations."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="Create an unreviewed template.")
    initialize.add_argument("--artifact", type=Path, required=True)
    initialize.add_argument("--output", type=Path, required=True)

    check = commands.add_parser("check", help="Validate and summarize a review.")
    check.add_argument("--artifact", type=Path, required=True)
    check.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()

    try:
        source_json = args.artifact.read_bytes()

        if args.command == "init":
            review = create_review(source_json)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(review.model_dump_json(indent=2) + "\n")

            print(f"Review template created: checks={len(review.checks)}.")
            print("All decisions remain not_reviewed. Fill in reviewer, verdicts and notes.")
            return

        status = evaluate_review(source_json, args.review.read_bytes())
    except FileExistsError:
        parser.exit(2, "Knowledge review failed: output already exists.\n")
    except ValidationError:
        # Validation errors may contain excerpts from private incident data.
        parser.exit(2, "Knowledge review failed: invalid artifact or review JSON.\n")
    except OSError:
        parser.exit(2, "Knowledge review failed: unable to read or write a file.\n")
    except ValueError as exc:
        parser.exit(2, f"Knowledge review failed: {exc}\n")

    print(f"Review status: {status.value}.")
    if status != ReviewStatus.PASSED:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
