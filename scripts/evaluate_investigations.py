import argparse
from pathlib import Path

from ai_incident_investigator.evaluation.dataset import (
    fixture_path,
    load_dataset,
)
from ai_incident_investigator.evaluation.runner import run_evaluation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate offline investigation pipeline scenarios."
    )

    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "evals" / "scenarios.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation-results.json",
    )

    args = parser.parse_args()

    try:
        dataset = load_dataset(args.dataset)

        inputs = {
            args.dataset.resolve(),
            *(
                fixture_path(
                    args.dataset.parent / "fixtures",
                    item,
                )
                for item in dataset.scenarios
            ),
        }

        if args.output.resolve() in inputs:
            raise ValueError("Evaluation output must not overwrite the dataset or log fixtures")

        result = run_evaluation(
            dataset,
            fixtures_dir=args.dataset.parent / "fixtures",
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            result.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Evaluation failed: {exc}") from None

    for scenario in result.scenarios:
        print(f"{'PASS' if scenario.passed else 'FAIL'} {scenario.scenario_id}")

        for check in scenario.checks:
            if not check.passed:
                print(f"  {check.name}: {check.description}")

    print(f"Offline pipeline: {result.passed_scenarios}/{len(result.scenarios)} scenarios passed.")
    print("LLM semantic quality: not evaluated.")
    print(f"Results: {args.output}")

    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
