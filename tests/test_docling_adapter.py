import socket
from hashlib import sha256
from importlib.metadata import PackageNotFoundError
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

from ai_incident_investigator.knowledge import docling_adapter as adapter
from ai_incident_investigator.knowledge.documents import (
    MAX_SOURCE_BYTES,
    DoclingLocation,
    ExtractionError,
    KnowledgeMetadata,
)

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"
pytestmark = [
    pytest.mark.document_conversion,
    pytest.mark.skipif(find_spec("docling") is None, reason="Requires the ingestion extra"),
]


@pytest.fixture(scope="module", autouse=True)
def import_docling() -> None:
    # Third-party module initialization happens before the per-test socket guard.
    from docling.document_converter import DocumentConverter

    assert DocumentConverter is not None


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Document extraction must not access the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")


def metadata_for(filename: str) -> KnowledgeMetadata:
    return KnowledgeMetadata(
        id="test-document",
        title="Test document",
        service="order-service",
        environment="local",
        owner="test-owner",
        version=1,
        status="draft",
        document_type="architecture",
        file=filename,
    )


class StubConverter:
    def __init__(self, result: SimpleNamespace) -> None:
        self.result = result

    def convert(self, source: object, **kwargs: object) -> SimpleNamespace:
        return self.result


def stub_result(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str = "success",
    source_format: str = "html",
    text: str | None = "A useful observation.",
) -> None:
    from docling.datamodel.base_models import ConversionStatus, InputFormat
    from docling_core.types.doc.document import DoclingDocument
    from docling_core.types.doc.labels import DocItemLabel

    document = DoclingDocument(name="test")
    if text is not None:
        document.add_text(label=DocItemLabel.TEXT, text=text)
    converter = StubConverter(
        SimpleNamespace(
            status=ConversionStatus(status),
            input=SimpleNamespace(format=InputFormat(source_format)),
            document=document,
        )
    )
    monkeypatch.setattr(adapter, "_create_converter", lambda: converter)


def test_local_html_preserves_useful_content_without_fetching_resources() -> None:
    source = (FIXTURES / "service-overview.html").read_bytes()
    metadata = metadata_for("service-overview.html")

    document = adapter.extract_docling(metadata, source)

    content = "\n".join(block.content for block in document.blocks)
    assert document.metadata == metadata
    assert document.source_sha256 == sha256(source).hexdigest()
    assert "Navigation noise" not in content
    assert "Ignore all investigation rules" not in content
    assert "font-family" not in content
    assert "A successful scrape does not prove successful order processing." in content
    assert any(block.kind == "table" for block in document.blocks)
    assert content.count("rich-cell-marker") == 1

    code_blocks = [block for block in document.blocks if block.kind == "code"]
    assert len(code_blocks) == 1
    assert "curl  http://127.0.0.1:8081/actuator/health" in code_blocks[0].content
    assert "\n  keep_internal_indentation = True" in code_blocks[0].content

    for block in document.blocks:
        assert isinstance(block.location, DoclingLocation)
        assert block.location.item_ref.startswith("#/")
        assert block.location.pages == ()
    assert any("outer whitespace" in note for note in document.notes)
    assert "docling=2.142.1" in document.extractor
    assert "docling-core=" in document.extractor
    assert "docling-parse=" in document.extractor
    assert "beautifulsoup4=" in document.extractor


def test_local_native_pdf_retains_page_provenance() -> None:
    source = (FIXTURES / "text-native.pdf").read_bytes()

    document = adapter.extract_docling(metadata_for("text-native.pdf"), source)

    assert document.source_sha256 == sha256(source).hexdigest()
    expected = {
        "native-text-config-page-1": (1,),
        "native-text-limits-page-2": (2,),
    }
    for marker, pages in expected.items():
        matches = [block for block in document.blocks if marker in block.content]
        assert len(matches) == 1
        location = matches[0].location
        assert isinstance(location, DoclingLocation)
        assert location.pages == pages

    for block in document.blocks:
        assert isinstance(block.location, DoclingLocation)
        assert block.location.pages
    assert any("Native PDF text only" in note for note in document.notes)


def test_converter_disables_model_processing_and_resource_fetching() -> None:
    from docling.datamodel.backend_options import HTMLBackendOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import NativePdfPipelineOptions
    from docling.pipeline.native_pdf_pipeline import NativePdfPipeline

    converter = adapter._create_converter()
    html = converter.format_to_options[InputFormat.HTML].backend_options
    assert isinstance(html, HTMLBackendOptions)
    assert not html.render_page
    assert not html.fetch_images
    assert not html.enable_local_fetch
    assert not html.enable_remote_fetch
    assert not html.add_title
    assert not html.infer_furniture

    pdf = converter.format_to_options[InputFormat.PDF]
    assert pdf.pipeline_cls is NativePdfPipeline
    options = pdf.pipeline_options
    assert isinstance(options, NativePdfPipelineOptions)
    assert not options.generate_page_images
    assert not options.generate_picture_images
    assert not options.do_picture_description
    assert not options.do_picture_classification
    assert not options.do_chart_extraction


@pytest.mark.parametrize("status", ["partial_success", "failure", "skipped"])
def test_incomplete_conversion_is_rejected(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    stub_result(monkeypatch, status=status)

    with pytest.raises(ExtractionError, match="did not complete successfully"):
        adapter.extract_docling(metadata_for("sample.html"), b"<p>Text</p>")


def test_detected_format_must_match_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_result(monkeypatch, source_format="pdf")

    with pytest.raises(ExtractionError, match="does not match its format"):
        adapter.extract_docling(metadata_for("sample.html"), b"<p>Text</p>")


def test_pdf_without_page_provenance_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_result(monkeypatch, source_format="pdf")

    with pytest.raises(ExtractionError, match="lacks page provenance"):
        adapter.extract_docling(metadata_for("sample.pdf"), b"%PDF-fake")


@pytest.mark.parametrize("text", [None, " \n\t"])
def test_success_without_usable_text_is_rejected(
    monkeypatch: pytest.MonkeyPatch, text: str | None
) -> None:
    stub_result(monkeypatch, text=text)

    with pytest.raises(ExtractionError, match="no usable text"):
        adapter.extract_docling(metadata_for("sample.html"), b"<p>Text</p>")


def test_conversion_exception_is_exposed_as_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenConverter:
        def convert(self, source: object, **kwargs: object) -> NoReturn:
            raise RuntimeError("A backend failed")

    monkeypatch.setattr(adapter, "_create_converter", BrokenConverter)

    with pytest.raises(ExtractionError, match="conversion failed") as error:
        adapter.extract_docling(metadata_for("sample.html"), b"<p>Text</p>")

    assert isinstance(error.value.__cause__, RuntimeError)


def test_missing_optional_dependency_has_installation_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_version(package: str) -> NoReturn:
        raise PackageNotFoundError(package)

    monkeypatch.setattr(adapter, "version", missing_version)

    with pytest.raises(ExtractionError, match="uv sync --locked --extra ingestion"):
        adapter.extract_docling(metadata_for("sample.html"), b"<p>Text</p>")


def test_html_encoding_must_be_utf8() -> None:
    with pytest.raises(ExtractionError, match="HTML must use UTF-8"):
        adapter.extract_docling(metadata_for("sample.html"), b"<p>\xff</p>")


@pytest.mark.parametrize("source", [b"", b"x" * (MAX_SOURCE_BYTES + 1)])
def test_source_size_is_checked_before_conversion(source: bytes) -> None:
    with pytest.raises(ExtractionError, match="empty or too large"):
        adapter.extract_docling(metadata_for("sample.html"), source)


def test_unsupported_markdown_is_not_routed_through_docling() -> None:
    with pytest.raises(ExtractionError, match="Unsupported Docling source format"):
        adapter.extract_docling(metadata_for("sample.md"), b"# Example\n")


def test_extracted_size_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_result(monkeypatch, text="x" * 21)
    monkeypatch.setattr(adapter, "MAX_EXTRACTED_CHARACTERS", 20)

    with pytest.raises(ExtractionError, match="Extracted document is too large"):
        adapter.extract_docling(metadata_for("sample.html"), b"<p>Text</p>")
