from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9-]{0,63}$"),
]

NonEmptyText = Annotated[
    str,
    Field(min_length=1, max_length=200),
]


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class RunbookMetadata(KnowledgeModel):
    id: Identifier
    title: NonEmptyText
    service: Identifier
    environment: Identifier
    owner: NonEmptyText
    version: Annotated[int, Field(strict=True, ge=1)]
    status: Literal["draft", "approved"]
    reviewed_by: NonEmptyText | None = None
    file: Annotated[
        str,
        Field(pattern=r"^[a-z][a-z0-9-]{0,63}\.md$"),
    ]

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if self.status == "approved" and self.reviewed_by is None:
            raise ValueError("Approved runbooks require reviewed_by")

        if self.status == "draft" and self.reviewed_by is not None:
            raise ValueError("Draft runbooks must not declare reviewed_by")

        return self


class RunbookCatalog(KnowledgeModel):
    schema_version: Literal[1]
    documents: tuple[RunbookMetadata, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_documents(self) -> Self:
        ids = [document.id for document in self.documents]
        files = [document.file for document in self.documents]

        if len(ids) != len(set(ids)):
            raise ValueError("Runbook IDs must be unique")

        if len(files) != len(set(files)):
            raise ValueError("Runbook files must be unique")

        return self


class RunbookDocument(KnowledgeModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    metadata: RunbookMetadata
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
