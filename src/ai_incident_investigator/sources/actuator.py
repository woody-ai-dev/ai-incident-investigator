from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ai_incident_investigator.investigations.reports import Evidence, EvidenceSource
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.settings import ActuatorTarget
from ai_incident_investigator.sources.context import ActuatorCollection

MAX_RESPONSE_BYTES = 64 * 1024

SNAPSHOT_LIMITATION = (
    "Actuator provides current snapshots, not historical observations. "
    "These snapshots do not establish the service state during the incident window."
)


class AppInfo(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)


class InfoResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app: AppInfo


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["UP", "DOWN", "OUT_OF_SERVICE", "UNKNOWN"]


@dataclass(frozen=True)
class Snapshot:
    payload: bytes
    observed_at: datetime
    reference: str
    status_code: int


class HttpActuatorCollector:
    def __init__(self, client: httpx.Client, target: ActuatorTarget) -> None:
        self.client = client
        self.target = target

    def collect(self, request: InvestigationRequest) -> ActuatorCollection:
        result = ActuatorCollection()

        if (request.service, request.environment) != (
            self.target.service,
            self.target.environment,
        ):
            result.issues.append(
                "Actuator collection skipped: no target is configured for this service/environment."
            )
            return result

        try:
            info_snapshot = self._read("info", allowed_statuses=(200,))
            info = InfoResponse.model_validate_json(info_snapshot.payload)
        except (httpx.HTTPError, ValueError):
            result.issues.append(
                "Actuator info could not be collected or validated; "
                "health collection was skipped because target identity could not be verified."
            )
            return result

        if (info.app.name, info.app.environment) != (
            request.service,
            request.environment,
        ):
            result.issues.append(
                "Actuator identity does not match the requested service/environment; "
                "context was rejected."
            )
            return result

        result.evidence.append(
            self._evidence(
                "info",
                f"name={info.app.name}, environment={info.app.environment}, "
                f"version={info.app.version}",
                info_snapshot,
                request,
            )
        )

        try:
            health_snapshot = self._read(
                "health",
                allowed_statuses=(200, 503),
            )
            health = HealthResponse.model_validate_json(health_snapshot.payload)

            if health_snapshot.status_code == 503 and health.status not in (
                "DOWN",
                "OUT_OF_SERVICE",
            ):
                raise ValueError("HTTP 503 requires DOWN or OUT_OF_SERVICE health status")

            result.evidence.append(
                self._evidence(
                    "health",
                    f"status={health.status}",
                    health_snapshot,
                    request,
                )
            )
        except (httpx.HTTPError, ValueError):
            result.issues.append("Actuator health could not be collected or validated.")

        result.issues.append(SNAPSHOT_LIMITATION)

        if any(
            not request.start_time <= item.start_time < request.end_time for item in result.evidence
        ):
            result.issues.append(
                "At least one Actuator snapshot was observed outside the requested incident window."
            )

        return result

    def _read(
        self,
        endpoint: str,
        *,
        allowed_statuses: tuple[int, ...],
    ) -> Snapshot:
        reference = str(self.client.build_request("GET", endpoint).url)

        with self.client.stream("GET", endpoint) as response:
            if response.status_code not in allowed_statuses:
                raise ValueError("Unexpected Actuator HTTP status")

            payload = bytearray()

            for chunk in response.iter_bytes(chunk_size=8192):
                if len(payload) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError("Actuator response exceeds the byte limit")

                payload.extend(chunk)

            return Snapshot(
                payload=bytes(payload),
                observed_at=datetime.now(UTC),
                reference=reference,
                status_code=response.status_code,
            )

    @staticmethod
    def _evidence(
        endpoint: str,
        observation: str,
        snapshot: Snapshot,
        request: InvestigationRequest,
    ) -> Evidence:
        return Evidence(
            id=f"actuator-{endpoint}",
            source=EvidenceSource.ACTUATOR,
            service=request.service,
            summary=(
                f"Current Actuator {endpoint} snapshot: {observation}; "
                f"HTTP {snapshot.status_code}. "
                "This is not historical incident data."
            ),
            reference=snapshot.reference,
            start_time=snapshot.observed_at,
        )
