from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class AttributeDefinition(DTO):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,49}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["string", "number", "boolean", "enum"] = "string"
    required: bool = False
    allowed_values: list[str] = Field(default_factory=list, max_length=100)
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    description: str = Field(default="", max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def consistent(self):
        if self.type == "enum" and not self.allowed_values:
            raise ValueError("Enum attributes need allowed values")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Minimum exceeds maximum")
        if self.unit and self.unit not in {"mm", "cm", "m", "g", "kg", "items", "pairs"}:
            raise ValueError("Unsupported canonical unit")
        return self


class CategoryDefinition(DTO):
    name: str = Field(min_length=1, max_length=80)
    identity_fields: list[str] = Field(
        default_factory=lambda: ["manufacturer", "model", "mpn", "size"]
    )
    attributes: list[AttributeDefinition] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [a.key for a in self.attributes]
        if len(set(keys)) != len(keys):
            raise ValueError("Attribute keys must be unique")
        if not {"manufacturer", "model"}.issubset(self.identity_fields):
            raise ValueError("Manufacturer and model must be identity fields")
        return self


class LoginInput(DTO):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)


class WorkspaceOut(DTO):
    id: str
    name: str
    role: str


class SessionOut(DTO):
    id: str
    email: str
    name: str
    csrf: str
    workspaces: list[WorkspaceOut]


class CategoryOut(DTO):
    id: str
    version_id: str
    version: int
    definition: CategoryDefinition


class ImportOut(DTO):
    id: str
    filename: str
    columns: list[str]
    rows: list[dict[str, str]]
    status: str
    mapping: dict[str, str]


class ImportMapping(DTO):
    category_id: str
    mapping: dict[str, str]


class ProductOut(DTO):
    id: str
    sku: str
    name: str
    manufacturer: str
    model: str
    mpn: str
    variant: dict[str, str]
    original: dict[str, str]
    attributes: dict[str, Any]
    approved: dict[str, Any]
    revision: int
    category_id: str
    completeness: float
    missing: list[str]
    validation_failures: int
    evidence_coverage: float


class SourceOut(DTO):
    id: str
    filename: str
    version: int
    status: str
    error: str | None
    active: bool
    embedding_space: str | None
    created_at: datetime


class ChunkOut(DTO):
    id: str
    text: str
    location: dict[str, Any]
    identifiers: dict[str, Any]


class SourceDetail(DTO):
    document: SourceOut
    chunks: list[ChunkOut]


class BatchInput(DTO):
    product_ids: list[str] = Field(min_length=1, max_length=100)
    attributes: list[str] = Field(default_factory=list, max_length=50)
    title: str = Field(default="Catalog enrichment", max_length=120)


class RunOut(DTO):
    available_chunks: list[str] = Field(default_factory=list)
    stale: bool = False
    id: str
    batch_id: str
    product_id: str
    schema_id: str
    status: str
    step: str
    error: str | None
    product_revision: int
    interrupt_id: str | None
    attempt: int
    metrics: dict[str, Any]
    created_at: datetime


class BatchOut(DTO):
    id: str
    title: str
    created_at: datetime
    runs: list[RunOut]


class EvidenceOut(DTO):
    id: str
    chunk_id: str
    document_id: str
    document_version: int
    filename: str
    quote: str
    identity_basis: dict[str, Any]
    location: dict[str, Any]


class CandidateOut(DTO):
    id: str
    run_id: str
    product_id: str
    attribute_key: str
    original_value: Any | None
    raw_value: Any | None
    normalized_value: Any | None
    status: str
    version: int
    validation: dict[str, Any]
    conflict: dict[str, Any]
    manual: bool
    evidence: list[EvidenceOut]


class ReviewDetail(DTO):
    run: RunOut
    product: ProductOut
    schema_definition: CategoryDefinition
    candidates: list[CandidateOut]


class FieldDecision(DTO):
    candidate_id: str
    version: int = Field(ge=1)
    action: Literal["approve", "reject", "edit"]
    value: Any | None = None
    reason: str = Field(default="", max_length=500)


class ReviewInput(DTO):
    interrupt_id: str
    product_revision: int
    idempotency_key: str = Field(min_length=8, max_length=100)
    decisions: list[FieldDecision] = Field(min_length=1, max_length=100)


class ReviewOut(DTO):
    id: str
    status: str
    error: str | None


class EventOut(DTO):
    sequence: int
    step: str
    details: dict[str, Any]
    created_at: datetime


class ExportInput(DTO):
    idempotency_key: str = Field(min_length=8, max_length=100)


class ExportOut(DTO):
    id: str
    row_count: int
    created_at: datetime


class ProposedValue(DTO):
    attribute_key: str
    raw_value: str | float | bool
    chunk_id: str
    quote: str = Field(min_length=1, max_length=4000)


class ExtractionOutput(DTO):
    values: list[ProposedValue] = Field(default_factory=list, max_length=100)
    limitation: str | None = None


class ValidationResult(DTO):
    valid: bool
    normalized: Any | None = None
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExampleCase(BaseModel):
    sku: str
    name: str
    title: str
    context: str
    outcome: str
    attributes: list[str]
    evidence_files: list[str]
    product_id: str | None = None
    run_id: str | None = None
    status: str = "not_started"


class ExampleCollection(BaseModel):
    title: str
    description: str
    version: str
    synthetic: bool
    cases: list[ExampleCase]
    sources: list[str]
    workspace_id: str | None = None
    sources_ready: int
    sources_total: int
    mode: str


class WalkthroughOut(DTO):
    workspace_id: str | None
    product: ProductOut | None
    run: RunOut | None
    sources: list[SourceOut]
    mode: str


class CheckpointOut(DTO):
    id: str
    created_at: datetime
    step: int
    next_nodes: list[str]
    interrupted: bool


class TimelineDecision(DTO):
    attribute_key: str
    candidate_id: str
    action: str
    reason: str


class TimelineReview(DTO):
    id: str
    status: str
    created_at: datetime
    decisions: list[TimelineDecision]


class RunTimelineOut(DTO):
    run_id: str
    status: str
    attempt: int
    events: list[EventOut]
    checkpoints: list[CheckpointOut]
    reviews: list[TimelineReview]
    truncated: bool
