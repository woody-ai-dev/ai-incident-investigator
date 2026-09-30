from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

from ai_incident_investigator.investigations.reports import Evidence, EvidenceSource
from ai_incident_investigator.investigations.schemas import InvestigationRequest


class LogEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    timestamp: AwareDatetime
    service: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=100)
    level: Literal["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
    message: str = Field(min_length=1, max_length=3900)

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(csl, value: object) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("timestamp must be an ISO 8601 string or a datetime object")

    @field_validator("timestamp")
    @classmethod
    def normilize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class LogCollection(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


def collect_logs(
    path: Path,
    request: InvestigationRequest,
    *,
    max_evidence: int = 100,
    max_scan_bytes: int = 5 * 1024 * 1024,
    max_line_bytes: int = 64 * 1024,
) -> LogCollection:
    """Read a bounded portion of a local JSONL file in file order."""

    if min(max_evidence, max_scan_bytes, max_line_bytes) < 1:
        raise ValueError("Collection limits must be positive")

    result = LogCollection()
    invalid_lines = 0
    scanned_bytes = 0
    line_number = 0

    try:
        with path.open("rb") as stream:
            while True:
                remaining = max_scan_bytes - scanned_bytes
                raw_line = stream.readline(min(max_line_bytes, remaining) + 1)
                if not raw_line:
                    break

                line_number += 1

                if len(raw_line) > remaining:
                    result.issues.append("Log scan byte limit reached; results are incomplete.")
                    break
                if len(raw_line) > max_line_bytes:
                    result.issues.append(
                        f"Line {line_number} exceeds the byte limit; log scan stopped."
                    )
                    break

                scanned_bytes += len(raw_line)
                if not raw_line.strip():
                    continue

                try:
                    entry = LogEntry.model_validate_json(raw_line)
                except ValidationError:
                    invalid_lines += 1
                    continue

                if (
                    entry.service != request.service
                    or entry.environment != request.environment
                    or not request.start_time <= entry.timestamp < request.end_time
                ):
                    continue

                if len(result.evidence) == max_evidence:
                    result.issues.append("Evidence limit reached; matching logs were omitted.")
                    break

                result.evidence.append(
                    Evidence(
                        id=f"log-{line_number}",
                        source=EvidenceSource.LOG,
                        service=entry.service,
                        summary=f"[{entry.level}] {entry.message}",
                        reference=f"local-jsonl:line:{line_number}",
                        start_time=entry.timestamp,
                    )
                )
    except OSError:
        result.issues.append("Log file could not be read; log coverage is incomplete.")

    if invalid_lines:
        result.issues.append(
            f"Skipped {invalid_lines} invalid log line(s); coverage is incomplete."
        )
    if not result.evidence and not result.issues:
        result.issues.append("Log file was read successfully, but no matching records were found.")

    return result
