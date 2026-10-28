from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from importlib.util import find_spec
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import httpx2 as httpx
import pytest
from openai import OpenAI

if TYPE_CHECKING:
    from tiktoken import Encoding

    from ai_incident_investigator.knowledge.embeddings import OpenAIEmbedder
    from ai_incident_investigator.knowledge.retrieval_chunks import RetrievalChunk

pytestmark = pytest.mark.skipif(find_spec("tiktoken") is None, reason="Requires retrieval extra")
Handler = Callable[[httpx.Request], httpx.Response]


class TokenCounter:
    def encode(self, text: str, *, disallowed_special: object) -> list[int]:
        assert disallowed_special == ()
        return [0] * ({"at-limit": 8192, "too-long": 8193}.get(text, 1))


@pytest.fixture
def make_embedder() -> Iterator[Callable[[Handler], OpenAIEmbedder]]:
    from ai_incident_investigator.knowledge.embeddings import OpenAIEmbedder

    clients: list[OpenAI] = []

    def factory(handler: Handler) -> OpenAIEmbedder:
        client = OpenAI(
            api_key="test-only",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        return OpenAIEmbedder(client, encoding=cast("Encoding", TokenCounter()))

    yield factory
    for client in clients:
        client.close()


def vector(value: float = 1.0) -> list[float]:
    return [value, *([0.0] * 1535)]


def result(index: int, embedding: list[float] | None = None) -> dict[str, object]:
    return {
        "object": "embedding",
        "index": index,
        "embedding": vector() if embedding is None else embedding,
    }


def response(
    data: list[dict[str, object]], model: str = "text-embedding-3-small"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": model,
            "data": data,
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        },
    )


def test_batches_preserve_input_order_and_accumulate_usage(
    make_embedder: Callable[[Handler], OpenAIEmbedder],
) -> None:
    sizes: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "text-embedding-3-small"
        texts = payload["input"]
        sizes.append(len(texts))
        return response(
            [
                result(i, vector(float(text.split("-")[1]) + 1))
                for i, text in reversed(list(enumerate(texts)))
            ]
        )

    embedder = make_embedder(handle)
    vectors = embedder.embed([f"text-{i}" for i in range(33)])

    assert sizes == [32, 1]
    assert [item[0] for item in vectors] == list(range(1, 34))
    assert embedder.total_tokens == 14
    assert embedder.spec.dimensions == 1536
    assert len(embedder.spec.fingerprint) == 64


@pytest.mark.parametrize("bad_text", ["", " \n\t", "too-long"])
def test_all_inputs_are_validated_before_any_request(
    make_embedder: Callable[[Handler], OpenAIEmbedder],
    bad_text: str,
) -> None:
    from ai_incident_investigator.knowledge.embeddings import EmbeddingError

    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Input validation must finish before the first API request")

    with pytest.raises(EmbeddingError):
        make_embedder(unexpected).embed(["valid"] * 32 + [bad_text])


def test_empty_sequence_does_not_call_api_and_exact_limit_is_accepted(
    make_embedder: Callable[[Handler], OpenAIEmbedder],
) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return response([result(0)])

    embedder = make_embedder(handle)
    assert embedder.embed([]) == []
    assert calls == []
    assert embedder.embed(["at-limit"]) == [vector()]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "data,model",
    [
        ([result(0)], "text-embedding-3-small"),
        ([result(0), result(0)], "text-embedding-3-small"),
        ([result(0), result(2)], "text-embedding-3-small"),
        ([result(-1), result(1)], "text-embedding-3-small"),
        ([result(0, [1.0]), result(1)], "text-embedding-3-small"),
        ([result(0, [0.0] * 1536), result(1)], "text-embedding-3-small"),
        ([result(0), result(1)], "unexpected-model"),
    ],
)
def test_malformed_responses_are_rejected(
    make_embedder: Callable[[Handler], OpenAIEmbedder],
    data: list[dict[str, object]],
    model: str,
) -> None:
    from ai_incident_investigator.knowledge.embeddings import EmbeddingError

    with pytest.raises(EmbeddingError):
        make_embedder(lambda request: response(data, model)).embed(["one", "two"])


@pytest.mark.parametrize(
    "vectors,count,dimensions",
    [
        ([], 1, 2),
        ([[1.0]], 1, 2),
        ([[0.0, 0.0]], 1, 2),
        ([[float("nan"), 1.0]], 1, 2),
        ([[float("inf"), 1.0]], 1, 2),
    ],
)
def test_vector_contract_rejects_invalid_data(
    vectors: list[list[float]],
    count: int,
    dimensions: int,
) -> None:
    from ai_incident_investigator.knowledge.embeddings import EmbeddingError, validate_vectors

    with pytest.raises(EmbeddingError):
        validate_vectors(vectors, count=count, dimensions=dimensions)


def test_sdk_error_is_sanitized(make_embedder: Callable[[Handler], OpenAIEmbedder]) -> None:
    from ai_incident_investigator.knowledge.embeddings import EmbeddingError

    embedder = make_embedder(
        lambda request: httpx.Response(
            500, json={"error": {"message": "secret-provider-details", "type": "server_error"}}
        )
    )
    with pytest.raises(EmbeddingError) as error:
        embedder.embed(["sample"])
    assert "secret-provider-details" not in str(error.value)
    assert "test-only" not in str(error.value)


def test_embedding_text_preserves_content_and_its_document_context() -> None:
    from ai_incident_investigator.knowledge.embeddings import embedding_text

    chunk = cast(
        "RetrievalChunk",
        SimpleNamespace(
            document=SimpleNamespace(title="Runbook"),
            section="Limits",
            content="Keep  spaces\n  indentation",
        ),
    )
    assert embedding_text(chunk) == "Runbook\n\nLimits\n\nKeep  spaces\n  indentation"


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param({"data": None}, id="null-data"),
        pytest.param({"data": {}}, id="data-not-a-list"),
        pytest.param({"data": [None, result(1)]}, id="null-data-entry"),
        pytest.param(
            {"data": [{"object": "embedding", "index": None, "embedding": vector()}, result(1)]},
            id="null-index",
        ),
        pytest.param(
            {"data": [result(0), {"object": "embedding", "index": True, "embedding": vector()}]},
            id="boolean-index",
        ),
        pytest.param({"usage": None}, id="null-usage"),
        pytest.param({"usage": {"prompt_tokens": 7, "total_tokens": None}}, id="null-total-tokens"),
        pytest.param(
            {"usage": {"prompt_tokens": 7, "total_tokens": -1}}, id="negative-total-tokens"
        ),
    ],
)
def test_malformed_successful_response_raises_domain_error(
    make_embedder: Callable[[Handler], OpenAIEmbedder],
    replacement: dict[str, object],
) -> None:
    from ai_incident_investigator.knowledge.embeddings import EmbeddingError

    payload = {
        "object": "list",
        "model": "text-embedding-3-small",
        "data": [result(0), result(1)],
        "usage": {"prompt_tokens": 7, "total_tokens": 7},
        **replacement,
    }
    embedder = make_embedder(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(EmbeddingError):
        embedder.embed(["one", "two"])
