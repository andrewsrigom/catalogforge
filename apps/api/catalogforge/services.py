import csv
import hashlib
import io
import json
import zipfile
from pathlib import PurePath
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import Principal
from .contracts import (
    BatchInput,
    CategoryDefinition,
    CategoryOut,
    ImportMapping,
    ProductOut,
    ReviewInput,
)
from .domain import normalize, pdf_header_present, present
from .models import (
    AuditEvent,
    Batch,
    Candidate,
    CatalogImport,
    Category,
    Evidence,
    Export,
    Outbox,
    Product,
    ProductRun,
    Review,
    SchemaVersion,
    SourceDocument,
    Workspace,
    uid,
)
from .storage import storage


async def get_scoped(db: AsyncSession, model, object_id: str, workspace_id: str, lock=False):
    query = select(model).where(model.id == object_id, model.workspace_id == workspace_id)
    if lock:
        query = query.with_for_update()
    item = await db.scalar(query)
    if item is None:
        raise HTTPException(404, "Record not found in this workspace")
    return item


async def audit(db: AsyncSession, actor: Principal, action: str, entity_id: str, details=None):
    db.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor_id=actor.user.id,
            action=action,
            entity_id=entity_id,
            details=details or {},
        )
    )


async def enqueue(
    db: AsyncSession, workspace_id: str, kind: str, entity_id: str, dedupe: str, payload=None
):
    if await db.scalar(select(Outbox.id).where(Outbox.dedupe_key == dedupe)):
        return
    db.add(
        Outbox(
            workspace_id=workspace_id,
            kind=kind,
            entity_id=entity_id,
            dedupe_key=dedupe,
            payload=payload or {},
        )
    )


async def current_schema(db: AsyncSession, workspace_id: str, category_id: str) -> SchemaVersion:
    category = await get_scoped(db, Category, category_id, workspace_id)
    schema = await db.scalar(
        select(SchemaVersion).where(
            SchemaVersion.workspace_id == workspace_id,
            SchemaVersion.category_id == category_id,
            SchemaVersion.version == category.current_version,
        )
    )
    assert schema is not None
    return schema


async def categories(db: AsyncSession, workspace_id: str) -> list[CategoryOut]:
    rows = (await db.scalars(select(Category).where(Category.workspace_id == workspace_id))).all()
    result = []
    for category in rows:
        schema = await current_schema(db, workspace_id, category.id)
        result.append(
            CategoryOut(
                id=category.id,
                version_id=schema.id,
                version=schema.version,
                definition=CategoryDefinition.model_validate(schema.definition),
            )
        )
    return result


async def save_schema(
    db: AsyncSession, actor: Principal, body: CategoryDefinition, category_id=None
):
    if category_id:
        category = await get_scoped(db, Category, category_id, actor.workspace_id, lock=True)
        category.current_version += 1
        category.name = body.name
    else:
        category = Category(
            id=uid(), workspace_id=actor.workspace_id, name=body.name, current_version=1
        )
        db.add(category)
        await db.flush()
    schema = SchemaVersion(
        id=uid(),
        workspace_id=actor.workspace_id,
        category_id=category.id,
        version=category.current_version,
        definition=body.model_dump(),
    )
    db.add(schema)
    await audit(db, actor, "schema.version_created", schema.id)
    await db.flush()
    return CategoryOut(
        id=category.id, version_id=schema.id, version=schema.version, definition=body
    )


def read_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "CSV must use UTF-8 encoding") from None
    reader = csv.DictReader(io.StringIO(decoded))
    columns = reader.fieldnames
    if (
        not columns
        or len(columns) > 100
        or any(not c for c in columns)
        or len(set(columns)) != len(columns)
    ):
        raise HTTPException(422, "CSV needs 1–100 unique, nonempty column headers")
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise HTTPException(422, "CSV row has a different number of columns")
        rows.append(dict(row))
        if len(rows) > 10000:
            raise HTTPException(422, "Catalog limit is 10,000 rows")
    if not rows:
        raise HTTPException(422, "CSV has no product rows")
    return list(columns), rows


async def preview_import(db: AsyncSession, actor: Principal, filename: str, content: bytes):
    columns, rows = read_csv(content)
    content_hash = hashlib.sha256(content).hexdigest()
    existing = await db.scalar(
        select(CatalogImport).where(
            CatalogImport.workspace_id == actor.workspace_id,
            CatalogImport.content_hash == content_hash,
        )
    )
    if existing:
        return existing
    item = CatalogImport(
        id=uid(),
        workspace_id=actor.workspace_id,
        filename=PurePath(filename).name,
        content_hash=content_hash,
        columns=columns,
        rows=rows,
        mapping={},
        status="preview",
    )
    db.add(item)
    await audit(db, actor, "catalog.previewed", item.id, {"rows": len(rows)})
    await db.flush()
    return item


async def confirm_import(db: AsyncSession, actor: Principal, import_id: str, body: ImportMapping):
    item = await get_scoped(db, CatalogImport, import_id, actor.workspace_id, lock=True)
    if item.status == "imported":
        if item.mapping != body.mapping:
            raise HTTPException(
                409, "This catalog has already been imported with a different mapping"
            )
        return item
    schema = await current_schema(db, actor.workspace_id, body.category_id)
    definition = CategoryDefinition.model_validate(schema.definition)
    allowed = (
        {"sku", "name", "manufacturer", "model", "mpn"}
        | set(definition.identity_fields)
        | {a.key for a in definition.attributes}
    )
    mapping = {key: value for key, value in body.mapping.items() if value}
    if not {"sku", "manufacturer", "model"}.issubset(mapping):
        raise HTTPException(422, "Map SKU, manufacturer and model before importing")
    if not set(mapping).issubset(allowed) or not set(mapping.values()).issubset(item.columns):
        raise HTTPException(422, "Mapping references an unknown field or source column")
    for row_number, row in enumerate(item.rows, start=2):
        values = {key: row[column] for key, column in mapping.items()}
        if not all(values.get(key, "").strip() for key in ["sku", "manufacturer", "model"]):
            raise HTTPException(422, f"Row {row_number} is missing product identity")
        attrs = {a.key: values.get(a.key, "") for a in definition.attributes}
        variant = {
            key: values.get(key, "")
            for key in definition.identity_fields
            if key not in {"manufacturer", "model", "mpn"}
        }
        db.add(
            Product(
                workspace_id=actor.workspace_id,
                import_id=item.id,
                row_number=row_number,
                category_id=body.category_id,
                sku=values["sku"],
                name=values.get("name") or values["sku"],
                manufacturer=values["manufacturer"],
                model=values["model"],
                mpn=values.get("mpn", ""),
                variant=variant,
                original=dict(row),
                attributes=attrs,
                approved={},
                revision=1,
                search_text=" ".join(values.values()),
            )
        )
    item.mapping = mapping
    item.status = "imported"
    await audit(db, actor, "catalog.imported", item.id, {"rows": len(item.rows)})
    await db.flush()
    return item


def product_view(product: Product, schema: SchemaVersion) -> ProductOut:
    definition = CategoryDefinition.model_validate(schema.definition)
    values = {**product.attributes, **product.approved}
    required = [a for a in definition.attributes if a.required]
    missing = [a.key for a in definition.attributes if not present(values.get(a.key))]
    filled = [a for a in required if present(values.get(a.key))]
    failures = sum(
        1
        for a in definition.attributes
        if present(values.get(a.key)) and not normalize(values[a.key], a).valid
    )
    data = {key: getattr(product, key) for key in ProductOut.model_fields if hasattr(product, key)}
    # Coverage measures approved, source-backed fields; manual edits are tracked separately below.
    backed = sum(1 for a in definition.attributes if a.key in product.approved)
    return ProductOut(
        **data,
        completeness=round(len(filled) / len(required) * 100, 1) if required else 100,
        missing=missing,
        validation_failures=failures,
        evidence_coverage=round(backed / len(definition.attributes) * 100, 1),
    )


async def upload_source(db: AsyncSession, actor: Principal, filename: str, content: bytes):
    filename = PurePath(filename.replace("\\", "/")).name
    suffix = filename.rsplit(".", 1)[-1].lower()
    if suffix not in {"txt", "csv", "pdf"}:
        raise HTTPException(422, "Upload a text-based PDF, UTF-8 TXT or CSV")
    if not content:
        raise HTTPException(422, "The uploaded file is empty")
    if suffix == "pdf" and not pdf_header_present(content):
        raise HTTPException(422, "File does not contain a valid PDF header")
    content_hash = hashlib.sha256(content).hexdigest()
    # Workspace lock serializes duplicate/version assignments.
    workspace = await get_workspace_lock(db, actor.workspace_id)
    duplicate = await db.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == actor.workspace_id,
            SourceDocument.content_hash == content_hash,
        )
    )
    if duplicate:
        return duplicate
    version = (
        await db.scalar(
            select(func.max(SourceDocument.version)).where(
                SourceDocument.workspace_id == actor.workspace_id,
                SourceDocument.filename == filename,
            )
        )
        or 0
    ) + 1
    doc_id = uid()
    key = f"{actor.workspace_id}/sources/{doc_id}.{suffix}"
    storage().put(key, content)
    doc = SourceDocument(
        id=doc_id,
        workspace_id=actor.workspace_id,
        filename=filename,
        content_hash=content_hash,
        version=version,
        storage_key=key,
        media_type=suffix,
        status="queued",
        active=True,
    )
    db.add(doc)
    workspace.source_revision += 1
    await db.flush()
    await enqueue(db, actor.workspace_id, "ingest", doc.id, f"ingest:{doc.id}")
    await audit(db, actor, "source.uploaded", doc.id, {"version": version})
    return doc


async def get_workspace_lock(db: AsyncSession, workspace_id: str) -> Workspace:
    workspace = await db.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    assert workspace is not None
    return workspace


async def start_batch(db: AsyncSession, actor: Principal, body: BatchInput):
    workspace = await get_workspace_lock(db, actor.workspace_id)
    batch = Batch(
        id=uid(),
        workspace_id=actor.workspace_id,
        title=body.title,
        requested_attributes=body.attributes,
        actor_id=actor.user.id,
    )
    db.add(batch)
    await db.flush()
    for product_id in dict.fromkeys(body.product_ids):
        product = await get_scoped(db, Product, product_id, actor.workspace_id)
        schema = await current_schema(db, actor.workspace_id, product.category_id)
        allowed = {a["key"] for a in schema.definition["attributes"]}
        if not set(body.attributes).issubset(allowed):
            raise HTTPException(422, "Selected attributes are not in the product schema")
        run = ProductRun(
            id=uid(),
            workspace_id=actor.workspace_id,
            batch_id=batch.id,
            product_id=product.id,
            schema_id=schema.id,
            product_revision=product.revision,
            source_revision=workspace.source_revision,
            status="queued",
            step="Queued",
            attempt=0,
            cancelled=False,
            available_chunks=[],
            metrics={},
        )
        db.add(run)
        await db.flush()
        await enqueue(db, actor.workspace_id, "enrich", run.id, f"enrich:{run.id}")
    await audit(db, actor, "batch.created", batch.id)
    return batch


async def submit_review(db: AsyncSession, actor: Principal, run_id: str, body: ReviewInput):
    request_hash = hashlib.sha256(
        json.dumps({"run_id": run_id, **body.model_dump()}, sort_keys=True).encode()
    ).hexdigest()
    await get_workspace_lock(db, actor.workspace_id)
    existing = await db.scalar(
        select(Review).where(
            Review.workspace_id == actor.workspace_id,
            Review.idempotency_key == body.idempotency_key,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key was used for a different review")
        return existing
    run = await get_scoped(db, ProductRun, run_id, actor.workspace_id, lock=True)
    product = await get_scoped(db, Product, run.product_id, actor.workspace_id, lock=True)
    schema = await current_schema(db, actor.workspace_id, product.category_id)
    workspace = await db.get(Workspace, actor.workspace_id)
    assert workspace is not None
    if run.status != "waiting_review" or run.interrupt_id != body.interrupt_id:
        raise HTTPException(409, "This review interrupt is no longer current; refresh")
    if (
        product.revision != body.product_revision
        or run.product_revision != product.revision
        or schema.id != run.schema_id
        or workspace.source_revision != run.source_revision
    ):
        raise HTTPException(
            409, "Stale proposals: product, schema or sources changed. Revalidate the product."
        )
    decisions = body.decisions
    if len({d.candidate_id for d in decisions}) != len(decisions):
        raise HTTPException(422, "Duplicate field decision")
    approved_keys = set()
    for decision in decisions:
        candidate = await get_scoped(db, Candidate, decision.candidate_id, actor.workspace_id)
        if candidate.run_id != run.id or candidate.version != decision.version:
            raise HTTPException(409, "Proposal version or run mismatch")
        if candidate.status in {"approved", "rejected"}:
            raise HTTPException(409, "Proposal already reviewed")
        if decision.action != "reject":
            if candidate.attribute_key in approved_keys:
                raise HTTPException(422, "Select only one value for each conflicting attribute")
            approved_keys.add(candidate.attribute_key)
            if present(product.attributes.get(candidate.attribute_key)) or present(
                product.approved.get(candidate.attribute_key)
            ):
                raise HTTPException(409, "Populated values cannot be overwritten")
            if decision.action == "approve" and candidate.status not in {
                "supported",
                "conflicting",
                "needs_review",
            }:
                raise HTTPException(
                    422, "Only supported evidence can be approved; edit manually or reject"
                )
            if candidate.status == "conflicting" and not decision.reason.strip():
                raise HTTPException(422, "Explain why you chose this conflicting value")
            if decision.action == "edit":
                if not decision.reason.strip():
                    raise HTTPException(422, "Manual edits require a reason")
                attr = next(
                    a
                    for a in CategoryDefinition.model_validate(schema.definition).attributes
                    if a.key == candidate.attribute_key
                )
                validation = normalize(decision.value, attr)
                if not validation.valid:
                    raise HTTPException(422, "; ".join(validation.errors))
    review = Review(
        id=uid(),
        workspace_id=actor.workspace_id,
        run_id=run.id,
        actor_id=actor.user.id,
        idempotency_key=body.idempotency_key,
        request_hash=request_hash,
        interrupt_id=body.interrupt_id,
        product_revision=body.product_revision,
        decisions=[d.model_dump() for d in decisions],
        status="queued",
    )
    db.add(review)
    run.status = "resuming"
    run.step = "Applying review"
    await db.flush()
    await enqueue(
        db, actor.workspace_id, "resume", run.id, f"resume:{review.id}", {"review_id": review.id}
    )
    await audit(db, actor, "review.submitted", review.id)
    return review


def csv_safe(value: Any) -> str:
    value = "" if value is None else str(value)
    # Preserve text while preventing spreadsheet formulas from executing.
    return "'" + value if value[:1] in {"=", "+", "-", "@", "\t", "\r"} else value


async def create_export(db: AsyncSession, actor: Principal, idempotency_key: str):
    await get_workspace_lock(db, actor.workspace_id)
    previous = await db.scalar(
        select(Export).where(
            Export.workspace_id == actor.workspace_id, Export.idempotency_key == idempotency_key
        )
    )
    if previous:
        return previous
    products = (
        await db.scalars(
            select(Product)
            .where(Product.workspace_id == actor.workspace_id)
            .order_by(Product.created_at, Product.row_number)
        )
    ).all()
    rows = []
    for product in products:
        imported = await get_scoped(db, CatalogImport, product.import_id, actor.workspace_id)
        row: dict[str, Any] = dict(product.original)
        for key, value in product.approved.items():
            column = imported.mapping.get(key, key)
            if not present(row.get(column)):
                row[column] = value
        rows.append(row)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    content = io.StringIO()
    writer = csv.DictWriter(content, fieldnames=columns)
    writer.writeheader()
    writer.writerows({k: csv_safe(v) for k, v in row.items()} for row in rows)
    report = []
    candidates = (
        await db.scalars(
            select(Candidate).where(
                Candidate.workspace_id == actor.workspace_id, Candidate.status == "approved"
            )
        )
    ).all()
    for candidate in candidates:
        evidence = (
            await db.scalars(
                select(Evidence).where(
                    Evidence.workspace_id == actor.workspace_id,
                    Evidence.candidate_id == candidate.id,
                )
            )
        ).all()
        run = await get_scoped(db, ProductRun, candidate.run_id, actor.workspace_id)
        report.append(
            {
                "product_id": candidate.product_id,
                "attribute": candidate.attribute_key,
                "schema_version_id": run.schema_id,
                "product_revision": run.product_revision,
                "proposal_version": candidate.version,
                "original_value": candidate.original_value,
                "proposed_raw_value": candidate.raw_value,
                "validation": candidate.validation,
                "conflict": candidate.conflict,
                "value": candidate.normalized_value,
                "manual_edit": candidate.manual,
                "source_supports_final_value": not candidate.manual,
                "run_id": candidate.run_id,
                "candidate_id": candidate.id,
                "evidence": [
                    {
                        "document_id": e.document_id,
                        "document_version": e.document_version,
                        "chunk_id": e.chunk_id,
                        "quote": e.quote,
                        "location": e.location,
                        "identity_basis": e.identity_basis,
                    }
                    for e in evidence
                ],
                "reviews": [
                    {
                        "review_id": r.id,
                        "actor_id": r.actor_id,
                        "created_at": r.created_at.isoformat(),
                        "decisions": [
                            decision
                            for decision in r.decisions
                            if decision["candidate_id"] == candidate.id
                        ],
                    }
                    for r in (
                        await db.scalars(
                            select(Review).where(
                                Review.workspace_id == actor.workspace_id,
                                Review.run_id == candidate.run_id,
                                Review.status == "applied",
                            )
                        )
                    ).all()
                ],
            }
        )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("catalog.csv", content.getvalue().encode("utf-8-sig"))
        package.writestr("evidence.json", json.dumps(report, indent=2))
        package.writestr(
            "README.txt",
            "CatalogForge export: only original and approved values.\nManual edits are explicitly labeled. Formula-like strings have a leading apostrophe for spreadsheet safety.\n",
        )
    export_id = uid()
    key = f"{actor.workspace_id}/exports/{export_id}.zip"
    storage().put(key, archive.getvalue())
    item = Export(
        id=export_id,
        workspace_id=actor.workspace_id,
        actor_id=actor.user.id,
        idempotency_key=idempotency_key,
        storage_key=key,
        row_count=len(rows),
    )
    db.add(item)
    await audit(db, actor, "catalog.exported", item.id, {"rows": len(rows)})
    await db.flush()
    return item


async def run_view(db: AsyncSession, run: ProductRun):
    from .contracts import RunOut

    result = RunOut.model_validate(run)
    if run.status in {"completed", "cancelled"}:
        return result
    product = await get_scoped(db, Product, run.product_id, run.workspace_id)
    schema = await current_schema(db, run.workspace_id, product.category_id)
    workspace = await db.get(Workspace, run.workspace_id)
    assert workspace is not None
    result.stale = (
        product.revision != run.product_revision
        or schema.id != run.schema_id
        or workspace.source_revision != run.source_revision
    )
    return result
