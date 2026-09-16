from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Scoped(Record):
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)

    @declared_attr.directive
    def __table_args__(cls):
        return (UniqueConstraint("workspace_id", "id"),)


def scoped_fk(column: str, table: str):
    return ForeignKeyConstraint(["workspace_id", column], [f"{table}.workspace_id", f"{table}.id"])


class Workspace(Record, Base):
    __tablename__ = "workspaces"
    name: Mapped[str]
    source_revision: Mapped[int] = mapped_column(default=0)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    password_hash: Mapped[str]


class Membership(Base):
    __tablename__ = "memberships"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    csrf: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Category(Scoped, Base):
    __tablename__ = "categories"
    name: Mapped[str]
    current_version: Mapped[int] = mapped_column(default=1)


class SchemaVersion(Scoped, Base):
    __tablename__ = "schema_versions"
    category_id: Mapped[str]
    version: Mapped[int]
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "category_id", "version"),
        scoped_fk("category_id", "categories"),
    )


class CatalogImport(Scoped, Base):
    __tablename__ = "catalog_imports"
    filename: Mapped[str]
    content_hash: Mapped[str]
    columns: Mapped[list[str]] = mapped_column(JSONB)
    mapping: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    rows: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default="preview")
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "content_hash"),
    )


class Product(Scoped, Base):
    __tablename__ = "products"
    import_id: Mapped[str]
    row_number: Mapped[int]
    category_id: Mapped[str]
    sku: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    manufacturer: Mapped[str] = mapped_column(index=True)
    model: Mapped[str] = mapped_column(index=True)
    mpn: Mapped[str] = mapped_column(index=True)
    variant: Mapped[dict[str, str]] = mapped_column(JSONB)
    original: Mapped[dict[str, str]] = mapped_column(JSONB)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    approved: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    revision: Mapped[int] = mapped_column(default=1)
    search_text: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "import_id", "row_number"),
        scoped_fk("import_id", "catalog_imports"),
        scoped_fk("category_id", "categories"),
    )


class ProductRevision(Scoped, Base):
    __tablename__ = "product_revisions"
    product_id: Mapped[str]
    revision: Mapped[int]
    values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "product_id", "revision"),
        scoped_fk("product_id", "products"),
    )


class SourceDocument(Scoped, Base):
    __tablename__ = "source_documents"
    filename: Mapped[str]
    content_hash: Mapped[str]
    version: Mapped[int] = mapped_column(default=1)
    storage_key: Mapped[str]
    media_type: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    embedding_space: Mapped[str | None]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "content_hash"),
        UniqueConstraint("workspace_id", "filename", "version"),
    )


class Chunk(Scoped, Base):
    __tablename__ = "chunks"
    document_id: Mapped[str]
    ordinal: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    location: Mapped[dict[str, Any]] = mapped_column(JSONB)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    embedding_space: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector())
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "document_id", "ordinal"),
        scoped_fk("document_id", "source_documents"),
        Index("ix_chunks_lexical", sql_text("to_tsvector('simple', text)"), postgresql_using="gin"),
    )


class Batch(Scoped, Base):
    __tablename__ = "batches"
    title: Mapped[str]
    requested_attributes: Mapped[list[str]] = mapped_column(JSONB)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ProductRun(Scoped, Base):
    __tablename__ = "product_runs"
    batch_id: Mapped[str]
    product_id: Mapped[str]
    schema_id: Mapped[str]
    product_revision: Mapped[int]
    source_revision: Mapped[int]
    status: Mapped[str] = mapped_column(default="queued", index=True)
    step: Mapped[str] = mapped_column(default="Queued")
    error: Mapped[str | None] = mapped_column(Text)
    interrupt_id: Mapped[str | None]
    attempt: Mapped[int] = mapped_column(default=0)
    cancelled: Mapped[bool] = mapped_column(default=False)
    available_chunks: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "batch_id", "product_id"),
        scoped_fk("batch_id", "batches"),
        scoped_fk("product_id", "products"),
        scoped_fk("schema_id", "schema_versions"),
    )


class Candidate(Scoped, Base):
    __tablename__ = "candidates"
    run_id: Mapped[str]
    product_id: Mapped[str]
    attribute_key: Mapped[str]
    original_value: Mapped[Any | None] = mapped_column(JSONB)
    raw_value: Mapped[Any | None] = mapped_column(JSONB)
    normalized_value: Mapped[Any | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(default=1)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    conflict: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    fingerprint: Mapped[str]
    manual: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "run_id", "attribute_key", "fingerprint"),
        scoped_fk("run_id", "product_runs"),
        scoped_fk("product_id", "products"),
    )


class Evidence(Scoped, Base):
    __tablename__ = "evidence"
    candidate_id: Mapped[str]
    chunk_id: Mapped[str]
    document_id: Mapped[str]
    document_version: Mapped[int]
    quote: Mapped[str] = mapped_column(Text)
    identity_basis: Mapped[dict[str, Any]] = mapped_column(JSONB)
    location: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("candidate_id", "candidates"),
        scoped_fk("chunk_id", "chunks"),
        scoped_fk("document_id", "source_documents"),
    )


class Review(Scoped, Base):
    __tablename__ = "reviews"
    run_id: Mapped[str]
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str]
    request_hash: Mapped[str]
    interrupt_id: Mapped[str]
    product_revision: Mapped[int]
    decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default="queued")
    error: Mapped[str | None]
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "idempotency_key"),
        scoped_fk("run_id", "product_runs"),
    )


class WorkflowEvent(Scoped, Base):
    __tablename__ = "workflow_events"
    sequence: Mapped[int] = mapped_column(
        BigInteger, unique=True, server_default=sql_text("nextval('event_sequence')")
    )
    run_id: Mapped[str | None]
    document_id: Mapped[str | None]
    step: Mapped[str]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        scoped_fk("run_id", "product_runs"),
        scoped_fk("document_id", "source_documents"),
    )


class Export(Scoped, Base):
    __tablename__ = "exports"
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str]
    storage_key: Mapped[str]
    row_count: Mapped[int]
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "idempotency_key"),
    )


class AuditEvent(Scoped, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str]
    entity_id: Mapped[str]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Outbox(Scoped, Base):
    __tablename__ = "outbox"
    kind: Mapped[str]
    entity_id: Mapped[str]
    dedupe_key: Mapped[str] = mapped_column(unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    delivered: Mapped[bool] = mapped_column(default=False, index=True)


class ProviderBudget(Scoped, Base):
    __tablename__ = "provider_budgets"
    scope_key: Mapped[str]
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB)
    calls: Mapped[int] = mapped_column(default=0)
    charged_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    charged_cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "scope_key"),
    )


class ProviderCall(Scoped, Base):
    __tablename__ = "provider_calls"
    scope_key: Mapped[str]
    entity_id: Mapped[str]
    operation: Mapped[str]
    model: Mapped[str]
    status: Mapped[str]
    reserved_tokens: Mapped[int] = mapped_column(BigInteger)
    charged_tokens: Mapped[int] = mapped_column(BigInteger)
    charged_cost_micros: Mapped[int] = mapped_column(BigInteger)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    pricing: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    duration_ms: Mapped[int | None]
    error_code: Mapped[str | None]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
