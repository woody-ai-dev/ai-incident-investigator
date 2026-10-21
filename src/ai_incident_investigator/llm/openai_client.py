import json
from collections.abc import Sequence
from datetime import UTC, datetime
from time import perf_counter_ns

from openai import APIError, OpenAI
from pydantic import ValidationError

from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError, AnalysisResult
from ai_incident_investigator.investigations.evidence_context import build_evidence_context
from ai_incident_investigator.investigations.reports import Evidence
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.llm.accounting import capture_usage
from ai_incident_investigator.llm.prompts import SYSTEM_PROMPT
from ai_incident_investigator.llm.response_schema import analysis_schema

MAX_INPUT_BYTES = 32_000


class OpenAIAnalyzer:
    def __init__(self, client: OpenAI, model: str) -> None:
        # One attempt per invocation: automatic retries could incur unrecorded usage.
        self.client = client.with_options(max_retries=0)
        self.model = model

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> AnalysisResult:
        payload = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "evidence_context": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in build_evidence_context(request, evidence)
                ],
                "missing_data": list(missing_data),
            },
            ensure_ascii=False,
        )

        if len(payload.encode("utf-8")) > MAX_INPUT_BYTES:
            raise AnalysisError("LLM input exceeds the configured size limit")

        started_at = datetime.now(UTC)
        started = perf_counter_ns()
        body: object = None
        try:
            raw = self.client.responses.with_raw_response.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=[{"role": "user", "content": payload}],
                text_format=analysis_schema([item.id for item in evidence]),
                max_output_tokens=2500,
                store=False,
                service_tier="default",
            )
            # Capture billing metadata before validating the generated structured answer.
            body = raw.http_response.json()
            response = raw.parse()
        except (APIError, ValidationError, ValueError) as exc:
            usage = capture_usage(
                body,
                requested_model=self.model,
                started_at=started_at,
                duration_ms=(perf_counter_ns() - started) // 1_000_000,
            )
            raise AnalysisError("LLM request failed or returned invalid data", usage=usage) from exc

        usage = capture_usage(
            body,
            requested_model=self.model,
            started_at=started_at,
            duration_ms=(perf_counter_ns() - started) // 1_000_000,
        )

        if response.status != "completed" or response.output_parsed is None:
            raise AnalysisError("LLM did not return a completed analysis", usage=usage)

        if any(
            part.type == "refusal"
            for item in response.output
            if item.type == "message"
            for part in item.content
        ):
            raise AnalysisError("LLM refused the analysis", usage=usage)

        return AnalysisResult(
            analysis=Analysis.model_validate(response.output_parsed.model_dump()), usage=usage
        )
