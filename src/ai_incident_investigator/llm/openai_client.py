import json
from collections.abc import Sequence

from openai import APIError, OpenAI
from pydantic import ValidationError

from ai_incident_investigator.investigations.analysis import Analysis, AnalysisError
from ai_incident_investigator.investigations.reports import Evidence
from ai_incident_investigator.investigations.schemas import InvestigationRequest
from ai_incident_investigator.llm.prompts import SYSTEM_PROMPT

MAX_INPUT_BYTES = 32_000


class OpenAIAnalyzer:
    def __init__(self, client: OpenAI, model: str) -> None:
        self.client = client
        self.model = model

    def analyze(
        self,
        request: InvestigationRequest,
        evidence: Sequence[Evidence],
        missing_data: Sequence[str],
    ) -> Analysis:
        payload = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "missing_data": list(missing_data),
            },
            ensure_ascii=False,
        )

        if len(payload.encode("utf-8")) > MAX_INPUT_BYTES:
            raise AnalysisError("LLM input exceeds the configured size limit")

        try:
            response = self.client.responses.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=[{"role": "user", "content": payload}],
                text_format=Analysis,
                max_output_tokens=2500,
                store=False,
            )
        except (APIError, ValidationError, ValueError) as exc:
            raise AnalysisError("LLM request failed or returned invalid data") from exc

        if response.status != "completed" or response.output_parsed is None:
            raise AnalysisError("LLM did not return a completed analysis")

        if any(
            part.type == "refusal"
            for item in response.output
            if item.type == "message"
            for part in item.content
        ):
            raise AnalysisError("LLM refused the analysis")

        return response.output_parsed
