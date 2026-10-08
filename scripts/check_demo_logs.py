import argparse
from pathlib import Path

from ai_incident_investigator.sources.logs import LogEntry


def check_logs(path: Path) -> None:
    count = 0
    timeout_found = False

    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue

            entry = LogEntry.model_validate_json(line)

            if entry.service != "order-service" or entry.environment != "local":
                raise ValueError("Unexpected service or environment")

            count += 1
            if entry.level == "ERROR" and "Payment request timed out (simulated)" in entry.message:
                timeout_found = True

    if not timeout_found:
        raise ValueError("Expected simulated payment timeout was not found")

    print(f"Validated {count} log records; simulated timeout found.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    check_logs(args.path)


if __name__ == "__main__":
    main()
