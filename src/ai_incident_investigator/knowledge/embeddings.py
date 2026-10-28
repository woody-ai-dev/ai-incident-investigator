import json
import math
from collections.abc import Sequence
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Protocol

from openai import OpenAI, OpenAIError
from pydantic import Field

from ai_incident_investigator.knowledge.models import KnowledgeModel
from ai_incident_investigator.knowledge.retrieval_chunks import RetrievalChunk

if TYPE_CHECKING:
    from tiktoken import Encoding

BATCH_SIZE = 32
MAX_INPUT_TOKENS = 8192


class EmbeddingError(ValueError):
    """Embedding input or provider output is invalid."""


class EmbeddingSpec(KnowledgeModel):
    provider: str = Field(default="openai", min_length=1)
    model: str = Field(default="text-embedding-3-small", min_length=1)
    dimensions: Annotated[int, Field(strict=True, ge=1, le=3072)] = 1536
    input_version: str = Field(default="title-section-v1", min_length=1)

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


class Embedder(Protocol):
    @property
    def spec(self) -> EmbeddingSpec: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def embedding_text(chunk: RetrievalChunk) -> str:
    return f"{chunk.document.title}\n\n{chunk.section}\n\n{chunk.content}"


def validate_vectors(vectors: Sequence[Sequence[float]], *, count: int, dimensions: int) -> None:
    if len(vectors) != count:
        raise EmbeddingError("Embedding response has an unexpected vector count")
    for vector in vectors:
        if not isinstance(vector, Sequence) or len(vector) != dimensions:
            raise EmbeddingError("Embedding vector has an unexpected dimension")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        ) or not any(vector):
            raise EmbeddingError("Embedding vector must be finite and nonzero")


class OpenAIEmbedder:
    spec = EmbeddingSpec()

    def __init__(self, client: OpenAI, *, encoding: "Encoding | None" = None) -> None:
        if encoding is None:
            import tiktoken

            try:
                encoding = tiktoken.get_encoding("cl100k_base")
            except (OSError, ValueError) as exc:
                raise EmbeddingError(
                    "Cannot load cl100k_base; prepare its tokenizer cache"
                ) from exc
        self._client = client
        self._encoding = encoding
        self.total_tokens = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # Validate the complete operation before its first billable request.
        for text in texts:
            if not text.strip():
                raise EmbeddingError("Embedding input must contain usable text")
            if len(self._encoding.encode(text, disallowed_special=())) > MAX_INPUT_TOKENS:
                raise EmbeddingError("Embedding input exceeds 8192 tokens; revise chunking")

        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            try:
                response = self._client.embeddings.create(
                    model=self.spec.model,
                    dimensions=self.spec.dimensions,
                    encoding_format="float",
                    input=batch,
                )
            except OpenAIError as exc:
                raise EmbeddingError("Embedding provider request failed") from exc
            try:
                if not isinstance(response.data, list) or any(
                    type(item.index) is not int for item in response.data
                ):
                    raise EmbeddingError("Embedding response has invalid data or indexes")
                data = sorted(response.data, key=lambda item: item.index)
                tokens = response.usage.total_tokens
                if type(tokens) is not int or tokens < 0:
                    raise EmbeddingError("Embedding response has invalid token usage")
            except (AttributeError, TypeError) as exc:
                raise EmbeddingError("Embedding response has an invalid structure") from exc
            if response.model != self.spec.model or [item.index for item in data] != list(
                range(len(batch))
            ):
                raise EmbeddingError("Embedding response has an unexpected model or indexes")
            result = [item.embedding for item in data]
            validate_vectors(result, count=len(batch), dimensions=self.spec.dimensions)
            vectors.extend(result)
            self.total_tokens += tokens
        return vectors
