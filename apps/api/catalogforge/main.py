from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import examples, services, timeline, walkthrough
from .auth import COOKIE, Principal, login, principal, reviewer, session_result, session_user
from .config import settings
from .contracts import (
    BatchInput,
    BatchOut,
    CandidateOut,
    CategoryDefinition,
    CategoryOut,
    ChunkOut,
    EventOut,
    EvidenceOut,
    ExampleCollection,
    ExportInput,
    ExportOut,
    ImportMapping,
    ImportOut,
    LoginInput,
    ProductOut,
    ReviewDetail,
    ReviewInput,
    ReviewOut,
    RunOut,
    RunTimelineOut,
    SessionOut,
    SourceDetail,
    SourceOut,
    WalkthroughOut,
)
from .db import session_dependency
from .models import (
    Batch,
    Candidate,
    Chunk,
    Evidence,
    Export,
    Product,
    ProductRevision,
    ProductRun,
    Review,
    SchemaVersion,
    SourceDocument,
    WorkflowEvent,
    uid,
)
from .storage import storage

app = FastAPI(
    title="CatalogForge API", version="0.1.0", openapi_url="/api/openapi.json", docs_url="/api/docs"
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings().trusted_hosts)
DB = Annotated[AsyncSession, Depends(session_dependency, scope="function")]
Actor = Annotated[Principal, Depends(principal)]
Reviewer = Annotated[Principal, Depends(reviewer)]


@app.middleware("http")
async def browser_security(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
        allowed = {
            settings().web_origin,
            str(request.base_url).rstrip("/"),
            "http://127.0.0.1:5288",
        }
        if origin not in allowed:
            return JSONResponse({"detail": "Cross-origin write rejected"}, status_code=403)
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal():
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if int(length) > settings().max_upload_bytes + 65536:
            return JSONResponse({"detail": "Upload exceeds 20 MB limit"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(IntegrityError)
async def conflict_handler(request, exc):
    return JSONResponse(
        {"detail": "A concurrent change conflicts with this operation. Refresh and retry."},
        status_code=409,
    )


@app.get("/api/health")
async def health(db: DB) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=SessionOut)
async def sign_in(body: LoginInput, response: Response, db: DB):
    return await login(db, body, response)


@app.get("/api/auth/me", response_model=SessionOut)
async def me(request: Request, db: DB):
    user, session = await session_user(request, db)
    return await session_result(db, user, session)


@app.post("/api/auth/logout", status_code=204)
async def sign_out(request: Request, response: Response, db: DB):
    _, session = await session_user(request, db)
    await db.delete(session)
    response.delete_cookie(COOKIE)


@app.get("/api/categories", response_model=list[CategoryOut])
async def list_categories(db: DB, actor: Actor):
    return await services.categories(db, actor.workspace_id)


@app.post("/api/categories", response_model=CategoryOut)
async def add_category(body: CategoryDefinition, db: DB, actor: Reviewer):
    return await services.save_schema(db, actor, body)


@app.put("/api/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: str, body: CategoryDefinition, db: DB, actor: Reviewer):
    return await services.save_schema(db, actor, body, category_id)


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read(settings().max_upload_bytes + 1)
    if len(data) > settings().max_upload_bytes:
        raise HTTPException(413, "Upload exceeds 20 MB limit")
    return data


@app.post("/api/imports/preview", response_model=ImportOut)
async def preview(file: UploadFile, db: DB, actor: Actor):
    return await services.preview_import(
        db, actor, file.filename or "catalog.csv", await read_upload(file)
    )


@app.post("/api/imports/{import_id}/confirm", response_model=ImportOut)
async def confirm(import_id: str, body: ImportMapping, db: DB, actor: Actor):
    return await services.confirm_import(db, actor, import_id, body)


async def view_product(db, actor, product):
    schema = await services.current_schema(db, actor.workspace_id, product.category_id)
    result = services.product_view(product, schema)
    backed = set(
        (
            await db.scalars(
                select(Candidate.attribute_key).where(
                    Candidate.workspace_id == actor.workspace_id,
                    Candidate.product_id == product.id,
                    Candidate.status == "approved",
                    Candidate.manual.is_(False),
                )
            )
        ).all()
    )
    result.evidence_coverage = round(len(backed) / len(schema.definition["attributes"]) * 100, 1)
    return result


@app.get("/api/products", response_model=list[ProductOut])
async def products(db: DB, actor: Actor, q: str = ""):
    query = select(Product).where(Product.workspace_id == actor.workspace_id).order_by(Product.sku)
    if q:
        query = query.where(
            Product.search_text.ilike("%" + q.replace("%", r"\%").replace("_", r"\_") + "%")
        )
    rows = (await db.scalars(query.limit(10000))).all()
    return [await view_product(db, actor, product) for product in rows]


@app.get("/api/products/{product_id}", response_model=ProductOut)
async def product_detail(product_id: str, db: DB, actor: Actor):
    product = await services.get_scoped(db, Product, product_id, actor.workspace_id)
    return await view_product(db, actor, product)


@app.get("/api/products/{product_id}/history")
async def product_history(product_id: str, db: DB, actor: Actor) -> list[dict[str, Any]]:
    await services.get_scoped(db, Product, product_id, actor.workspace_id)
    rows = (
        await db.scalars(
            select(ProductRevision)
            .where(
                ProductRevision.workspace_id == actor.workspace_id,
                ProductRevision.product_id == product_id,
            )
            .order_by(ProductRevision.revision)
        )
    ).all()
    return [
        {
            "revision": r.revision,
            "values": r.values,
            "actor_id": r.actor_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.get("/api/sources", response_model=list[SourceOut])
async def sources(db: DB, actor: Actor):
    return (
        await db.scalars(
            select(SourceDocument)
            .where(SourceDocument.workspace_id == actor.workspace_id)
            .order_by(SourceDocument.created_at.desc())
        )
    ).all()


@app.post("/api/sources", response_model=SourceOut)
async def upload_source(file: UploadFile, db: DB, actor: Actor):
    return await services.upload_source(
        db, actor, file.filename or "source.txt", await read_upload(file)
    )


@app.get("/api/sources/{document_id}", response_model=SourceDetail)
async def source_detail(document_id: str, db: DB, actor: Actor):
    doc = await services.get_scoped(db, SourceDocument, document_id, actor.workspace_id)
    chunks = (
        await db.scalars(
            select(Chunk)
            .where(Chunk.workspace_id == actor.workspace_id, Chunk.document_id == doc.id)
            .order_by(Chunk.ordinal)
        )
    ).all()
    return SourceDetail(
        document=SourceOut.model_validate(doc), chunks=[ChunkOut.model_validate(c) for c in chunks]
    )


@app.get("/api/sources/{document_id}/file")
async def source_file(document_id: str, db: DB, actor: Actor):
    doc = await services.get_scoped(db, SourceDocument, document_id, actor.workspace_id)
    return FileResponse(
        storage().path(doc.storage_key),
        filename=doc.filename,
        media_type="application/octet-stream",
    )


@app.post("/api/sources/{document_id}/retry", response_model=SourceOut)
async def retry_source(document_id: str, db: DB, actor: Actor):
    doc = await services.get_scoped(db, SourceDocument, document_id, actor.workspace_id, lock=True)
    if doc.status != "failed":
        raise HTTPException(409, "Only failed documents can be retried")
    doc.status, doc.error = "queued", None
    await services.enqueue(db, actor.workspace_id, "ingest", doc.id, f"retry:{doc.id}:{uid()}")
    return doc


@app.post("/api/batches", response_model=BatchOut)
async def start_batch(body: BatchInput, db: DB, actor: Actor):
    batch = await services.start_batch(db, actor, body)
    runs = (
        await db.scalars(
            select(ProductRun).where(
                ProductRun.workspace_id == actor.workspace_id, ProductRun.batch_id == batch.id
            )
        )
    ).all()
    return BatchOut(
        id=batch.id,
        title=batch.title,
        created_at=batch.created_at,
        runs=[await services.run_view(db, r) for r in runs],
    )


@app.get("/api/batches", response_model=list[BatchOut])
async def batches(db: DB, actor: Actor):
    items = (
        await db.scalars(
            select(Batch)
            .where(Batch.workspace_id == actor.workspace_id)
            .order_by(Batch.created_at.desc())
        )
    ).all()
    result = []
    for batch in items:
        runs = (
            await db.scalars(
                select(ProductRun).where(
                    ProductRun.workspace_id == actor.workspace_id, ProductRun.batch_id == batch.id
                )
            )
        ).all()
        result.append(
            BatchOut(
                id=batch.id,
                title=batch.title,
                created_at=batch.created_at,
                runs=[await services.run_view(db, r) for r in runs],
            )
        )
    return result


@app.get("/api/reviews", response_model=list[RunOut])
async def review_queue(db: DB, actor: Actor):
    runs = (
        await db.scalars(
            select(ProductRun)
            .where(
                ProductRun.workspace_id == actor.workspace_id,
                ProductRun.status.in_(["waiting_review", "resuming"]),
            )
            .order_by(ProductRun.created_at)
        )
    ).all()
    return [await services.run_view(db, run) for run in runs]


@app.get("/api/runs/{run_id}", response_model=ReviewDetail)
async def review_detail(run_id: str, db: DB, actor: Actor):
    run = await services.get_scoped(db, ProductRun, run_id, actor.workspace_id)
    product = await services.get_scoped(db, Product, run.product_id, actor.workspace_id)
    schema = await services.get_scoped(db, SchemaVersion, run.schema_id, actor.workspace_id)
    candidates = (
        await db.scalars(
            select(Candidate)
            .where(Candidate.workspace_id == actor.workspace_id, Candidate.run_id == run.id)
            .order_by(Candidate.attribute_key, Candidate.created_at)
        )
    ).all()
    result = []
    for candidate in candidates:
        links = (
            await db.execute(
                select(Evidence, SourceDocument.filename)
                .join(SourceDocument, Evidence.document_id == SourceDocument.id)
                .where(
                    Evidence.workspace_id == actor.workspace_id,
                    Evidence.candidate_id == candidate.id,
                )
            )
        ).all()
        evidence = [
            EvidenceOut(
                **{key: getattr(e, key) for key in EvidenceOut.model_fields if key != "filename"},
                filename=filename,
            )
            for e, filename in links
        ]
        result.append(
            CandidateOut(
                **{
                    key: getattr(candidate, key)
                    for key in CandidateOut.model_fields
                    if key != "evidence"
                },
                evidence=evidence,
            )
        )
    return ReviewDetail(
        run=await services.run_view(db, run),
        product=await view_product(db, actor, product),
        schema_definition=CategoryDefinition.model_validate(schema.definition),
        candidates=result,
    )


@app.post("/api/runs/{run_id}/review", response_model=ReviewOut)
async def review(run_id: str, body: ReviewInput, db: DB, actor: Reviewer):
    return await services.submit_review(db, actor, run_id, body)


@app.get("/api/review-decisions/{review_id}", response_model=ReviewOut)
async def review_status(review_id: str, db: DB, actor: Actor):
    return await services.get_scoped(db, Review, review_id, actor.workspace_id)


@app.post("/api/runs/{run_id}/cancel", response_model=RunOut)
async def cancel(run_id: str, db: DB, actor: Actor):
    await services.get_workspace_lock(db, actor.workspace_id)
    run = await services.get_scoped(db, ProductRun, run_id, actor.workspace_id, lock=True)
    if run.status == "completed":
        raise HTTPException(409, "Completed run cannot be cancelled")
    run.cancelled, run.status, run.step = True, "cancelled", "Cancelled"
    await services.audit(db, actor, "run.cancelled", run.id)
    return run


@app.post("/api/runs/{run_id}/retry", response_model=RunOut)
async def retry(run_id: str, db: DB, actor: Actor):
    await services.get_workspace_lock(db, actor.workspace_id)
    run = await services.get_scoped(db, ProductRun, run_id, actor.workspace_id, lock=True)
    if run.status != "failed":
        raise HTTPException(409, "Only failed runs can be retried")
    run.status, run.error, run.cancelled = "queued", None, False
    reviews = (
        await db.scalars(
            select(Review)
            .where(
                Review.workspace_id == actor.workspace_id,
                Review.run_id == run.id,
                Review.status == "failed",
            )
            .order_by(Review.created_at.desc())
        )
    ).all()
    payload = {"review_id": reviews[0].id} if reviews else {}
    await services.enqueue(
        db,
        actor.workspace_id,
        "resume" if reviews else "enrich",
        run.id,
        f"retry:{run.id}:{uid()}",
        payload,
    )
    return run


@app.post("/api/runs/{run_id}/revalidate", response_model=BatchOut)
async def revalidate(run_id: str, db: DB, actor: Actor):
    await services.get_workspace_lock(db, actor.workspace_id)
    run = await services.get_scoped(db, ProductRun, run_id, actor.workspace_id, lock=True)
    if run.status != "completed":
        run.cancelled, run.status = True, "cancelled"
    batch = await services.start_batch(
        db, actor, BatchInput(product_ids=[run.product_id], title="Evidence revalidation")
    )
    runs = (
        await db.scalars(
            select(ProductRun).where(
                ProductRun.workspace_id == actor.workspace_id, ProductRun.batch_id == batch.id
            )
        )
    ).all()
    return BatchOut(
        id=batch.id,
        title=batch.title,
        created_at=batch.created_at,
        runs=[await services.run_view(db, r) for r in runs],
    )


@app.get("/api/runs/{run_id}/events", response_model=list[EventOut])
async def events(run_id: str, db: DB, actor: Actor, after: int = 0):
    await services.get_scoped(db, ProductRun, run_id, actor.workspace_id)
    return (
        await db.scalars(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.workspace_id == actor.workspace_id,
                WorkflowEvent.run_id == run_id,
                WorkflowEvent.sequence > after,
            )
            .order_by(WorkflowEvent.sequence)
            .limit(500)
        )
    ).all()


@app.post("/api/exports", response_model=ExportOut)
async def export(body: ExportInput, db: DB, actor: Actor):
    return await services.create_export(db, actor, body.idempotency_key)


@app.get("/api/exports", response_model=list[ExportOut])
async def exports(db: DB, actor: Actor):
    return (
        await db.scalars(
            select(Export)
            .where(Export.workspace_id == actor.workspace_id)
            .order_by(Export.created_at.desc())
        )
    ).all()


@app.get("/api/exports/{export_id}/file")
async def export_file(export_id: str, db: DB, actor: Actor):
    export = await services.get_scoped(db, Export, export_id, actor.workspace_id)
    return FileResponse(
        storage().path(export.storage_key),
        filename=f"catalogforge-{export.id[:8]}.zip",
        media_type="application/zip",
    )


@app.get("/api/operations")
async def operational_status(db: DB, actor: Actor) -> dict[str, Any]:
    from .operations import summary

    return await summary(db, actor.workspace_id)


@app.get("/api/settings")
async def provider_status(actor: Actor) -> dict[str, Any]:
    config = settings()
    return {
        "mode": config.ai_mode,
        "chat_model": config.chat_model,
        "embedding_space": config.embedding_space,
        "credentials_configured": bool(config.openai_api_key.get_secret_value()),
        "provider_ready": config.ai_mode == "fixture"
        or bool(config.openai_api_key.get_secret_value()),
        "ai_limits": {
            "input_tokens": config.ai_max_input_tokens,
            "output_tokens": config.ai_max_output_tokens,
            "provider_retries": config.ai_provider_retries,
            "scope_calls": config.ai_scope_max_calls,
            "scope_tokens": config.ai_scope_max_tokens,
            "workspace_calls": config.ai_workspace_max_calls,
            "workspace_tokens": config.ai_workspace_max_tokens,
            "workspace_budget_usd": str(config.ai_workspace_budget_usd)
            if config.ai_workspace_budget_usd is not None
            else None,
            "pricing_configured": config.ai_chat_input_usd_per_million is not None,
            "pricing_date": config.ai_pricing_date or None,
        },
        "max_retrieval_rounds": config.max_retrieval_rounds,
        "max_run_seconds": config.max_run_seconds,
        "worker_concurrency": config.worker_concurrency,
        "fixture_limitation": "Deterministic synthetic records only. Fixture results do not measure live model quality.",
        "prompt_version": "catalogforge-extraction-v1",
    }


@app.get("/api/overview")
async def overview(db: DB, actor: Actor) -> dict[str, Any]:
    products = (
        await db.scalars(select(Product).where(Product.workspace_id == actor.workspace_id))
    ).all()
    runs = (
        await db.scalars(select(ProductRun).where(ProductRun.workspace_id == actor.workspace_id))
    ).all()
    docs = (
        await db.scalars(
            select(SourceDocument).where(SourceDocument.workspace_id == actor.workspace_id)
        )
    ).all()
    proposals = (
        await db.scalars(select(Candidate).where(Candidate.workspace_id == actor.workspace_id))
    ).all()
    events = (
        await db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.workspace_id == actor.workspace_id)
            .order_by(WorkflowEvent.sequence.desc())
            .limit(8)
        )
    ).all()
    return {
        "products": len(products),
        "sources_ready": sum(d.status == "ready" and d.active for d in docs),
        "processing": sum(r.status in {"queued", "processing", "resuming"} for r in runs),
        "waiting_review": sum(r.status == "waiting_review" for r in runs),
        "conflicts": sum(c.status == "conflicting" for c in proposals),
        "approved_fields": sum(c.status == "approved" for c in proposals),
        "failed": sum(r.status == "failed" for r in runs),
        "events": [EventOut.model_validate(e).model_dump(mode="json") for e in events],
    }


@app.get("/api/examples", response_model=ExampleCollection)
async def example_collection(db: DB, actor: Actor):
    return await examples.collection(db, actor)


@app.post("/api/examples/install", response_model=ExampleCollection)
async def install_examples(db: DB, actor: Reviewer):
    return await examples.install(db, actor)


@app.post("/api/examples/{sku}/run", response_model=RunOut)
async def run_example(sku: str, db: DB, actor: Reviewer):
    return await services.run_view(db, await examples.start(db, actor, sku))


@app.get("/api/examples/files/{filename}")
async def example_file(filename: str, actor: Actor):
    allowed = {
        "northstar-examples.zip": examples.ROOT / "northstar-examples.zip",
        "catalog.csv": examples.ROOT / "catalog.csv",
        **{name: examples.ROOT / "sources" / name for name in examples.manifest()["sources"]},
    }
    if filename not in allowed:
        raise HTTPException(404, "Example file not found")
    return FileResponse(allowed[filename], filename=filename)


@app.get("/api/walkthrough", response_model=WalkthroughOut)
async def walkthrough_state(db: DB, actor: Actor):
    return await walkthrough.state(db, actor)


@app.post("/api/walkthrough", response_model=WalkthroughOut)
async def install_walkthrough(db: DB, actor: Reviewer):
    return await walkthrough.install(db, actor)


@app.post("/api/walkthrough/start", response_model=RunOut)
async def start_walkthrough(db: DB, actor: Reviewer):
    return await walkthrough.start(db, actor)


@app.get("/api/runs/{run_id}/timeline", response_model=RunTimelineOut)
async def run_timeline(run_id: str, db: DB, actor: Actor):
    return await timeline.execution_timeline(db, actor, run_id)
