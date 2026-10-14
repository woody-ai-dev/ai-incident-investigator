from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_incident_investigator.investigations.reports import Evidence, EvidenceSource
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.sources.context import ActuatorCollection
from ai_incident_investigator.sources.metrics import MetricsCollection


class DatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expectations(DatasetModel):
    log_evidence: list[Evidence] = Field(default_factory=list)
    missing_data_contains: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        ids = [item.id for item in self.log_evidence]

        if len(ids) != len(set(ids)):
            raise ValueError("Expected evidence IDs must be unique")

        if any(item.source != EvidenceSource.LOG for item in self.log_evidence):
            raise ValueError("Expected log evidence must use the log source")

        return self


class Scenario(DatasetModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    description: str = Field(min_length=1, max_length=1000)

    request: InvestigationRequest
    log_file: str = Field(pattern=r"^[a-z][a-z0-9_-]*\.jsonl$")

    metrics: MetricsCollection | None = None
    actuator: ActuatorCollection | None = None

    expected: Expectations
    review_questions: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_recorded_sources(self) -> Self:
        if any(item.service != self.request.service for item in self.expected.log_evidence):
            raise ValueError("Expected logs must belong to the requested service")

        for collection, source in (
            (self.metrics, EvidenceSource.METRIC),
            (self.actuator, EvidenceSource.ACTUATOR),
        ):
            if collection is None:
                continue

            for item in collection.evidence:
                if item.source != source or item.service != self.request.service:
                    raise ValueError("Recorded evidence must match its source and service")

                if source == EvidenceSource.ACTUATOR and item.end_time is not None:
                    raise ValueError("Actuator evidence must be a point-in-time snapshot")

        ids = [item.id for item in self.expected.log_evidence]

        for collection in (self.metrics, self.actuator):
            if collection is not None:
                ids.extend(item.id for item in collection.evidence)

        if len(ids) != len(set(ids)):
            raise ValueError("Scenario evidence IDs must be unique across sources")

        return self


class Dataset(DatasetModel):
    version: Literal[1]
    scenarios: list[Scenario] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_scenarios(self) -> Self:
        ids = [item.id for item in self.scenarios]

        if len(ids) != len(set(ids)):
            raise ValueError("Scenario IDs must be unique")

        return self


def fixture_path(fixtures_dir: Path, scenario: Scenario) -> Path:
    root = fixtures_dir.resolve()
    path = (root / scenario.log_file).resolve()

    if path.parent != root or not path.is_file():
        raise ValueError(f"Missing or invalid log fixture for scenario {scenario.id}")

    return path


def load_dataset(path: Path) -> Dataset:
    dataset = Dataset.model_validate_json(path.read_bytes())

    for scenario in dataset.scenarios:
        fixture_path(path.parent / "fixtures", scenario)

    return dataset
