import hashlib
import json
import re
import time
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select

from .config import settings
from .contracts import AttributeDefinition, CategoryDefinition
from .db import transaction
from .domain import identity_match, normalize, present
from .models import (
    AuditEvent,
    Batch,
    Candidate,
    Chunk,
    Evidence,
    Membership,
    Product,
    ProductRevision,
    ProductRun,
    Review,
    SchemaVersion,
    SourceDocument,
    WorkflowEvent,
)
from .providers import IDENTITY_PROMPT_VERSION, PROMPT_VERSION, extract
from .retrieval import retrieval_tool
from .services import current_schema, get_scoped, get_workspace_lock


class EnrichState(TypedDict, total=False):
    workspace_id: str
    run_id: str
    identity: dict[str, Any]
    values: dict[str, Any]
    attributes: list[dict[str, Any]]
    round: int
    passages: list[dict[str, Any]]
    available: list[str]
    extracted: list[dict[str, Any]]
    extracted_passages: list[str]
    candidates: list[dict[str, Any]]
    limitation: str | None
    review_id: str
    pending: int
    started: float
    metrics: dict[str, Any]


async def step(state: EnrichState, label: str):
    async with transaction() as db:
        run = await get_scoped(db, ProductRun, state["run_id"], state["workspace_id"])
        if run.cancelled:
            raise ValueError("Run cancelled by a workspace member")
        db.add(WorkflowEvent(workspace_id=state["workspace_id"], run_id=run.id, step=label))
        run.step = label


async def inspect_product(state: EnrichState):
    await step(state, "Inspecting missing attributes")
    async with transaction() as db:
        run = await get_scoped(db, ProductRun, state["run_id"], state["workspace_id"])
        product = await get_scoped(db, Product, run.product_id, state["workspace_id"])
        schema = await get_scoped(db, SchemaVersion, run.schema_id, state["workspace_id"])
        batch = await get_scoped(db, Batch, run.batch_id, state["workspace_id"])
        values = {**product.attributes, **product.approved}
        attrs = [
            a
            for a in schema.definition["attributes"]
            if not batch.requested_attributes
            or a["key"] in batch.requested_attributes
            or present(values.get(a["key"]))
        ]
        return {
            "identity": {
                "manufacturer": product.manufacturer,
                "model": product.model,
                "mpn": product.mpn,
                "variant": product.variant,
            },
            "values": values,
            "attributes": attrs,
            "round": 0,
            "passages": [],
            "available": [],
            "extracted": [],
            "extracted_passages": [],
            "candidates": [],
            "started": time.time(),
            "metrics": {
                "prompt_version": PROMPT_VERSION,
                "identity_prompt_version": IDENTITY_PROMPT_VERSION,
                "mode": settings().ai_mode,
                "chat_model": settings().chat_model
                if settings().ai_mode == "real"
                else "deterministic-v1",
                "embedding_space": settings().embedding_space,
                "model_calls": 0,
                "tokens": None,
                "cost": None,
                "rejected_identity_passages": 0,
            },
        }


async def retrieve(state: EnrichState):
    await step(state, "Finding supporting passages")
    identity = state["identity"]
    query = " ".join(
        [
            identity["manufacturer"],
            identity["model"],
            identity.get("mpn", ""),
            *identity["variant"].values(),
        ]
    )
    tool = retrieval_tool(state["workspace_id"], identity, limit=12 if state["round"] == 0 else 40)
    passages = await tool.ainvoke({"query": query})
    available = list(dict.fromkeys([*state["available"], *[p["id"] for p in passages]]))
    async with transaction() as db:
        run = await get_scoped(db, ProductRun, state["run_id"], state["workspace_id"])
        run.available_chunks = available
    return {"passages": passages, "available": available, "round": state["round"] + 1}


async def check_identity(state: EnrichState):
    await step(state, "Checking product match")
    accepted = []
    rejected = 0
    for passage in state["passages"]:
        match = identity_match(state["identity"], passage["identifiers"])
        if match["applies"]:
            accepted.append({**passage, "identity_basis": match})
        else:
            rejected += 1
    metrics = {
        **state["metrics"],
        "rejected_identity_passages": rejected,
        "retrieval_rounds": state["round"],
        "applicable_passages": len(accepted),
    }
    return {"passages": accepted, "metrics": metrics}


async def extract_values(state: EnrichState):
    await step(state, "Extracting proposed values")
    if not state["passages"]:
        return {"limitation": "No source explicitly identifies this product and variant"}
    passage_ids = {passage["id"] for passage in state["passages"]}
    extracted_ids = set(state.get("extracted_passages", []))
    if passage_ids <= extracted_ids:
        return {}  # A wider retrieval found no new evidence; do not pay to extract it again.
    result, usage = await extract(
        {
            "identity": state["identity"],
            "attributes": state["attributes"],
            "passages": state["passages"],
        }
    )
    combined = {json.dumps(v, sort_keys=True): v for v in state["extracted"]}
    for value in result.values:
        combined[json.dumps(value.model_dump(), sort_keys=True)] = value.model_dump()
    return {
        "extracted": list(combined.values()),
        "extracted_passages": sorted(extracted_ids | passage_ids),
        "limitation": result.limitation,
        "metrics": {
            **state["metrics"],
            "model_calls": state["metrics"]["model_calls"] + usage["model_calls"],
            "tokens": usage.get("tokens"),
        },
    }


def literal_value_supported(raw: Any, quote: str) -> bool:
    if isinstance(raw, bool):
        return bool(re.search(r"\b(true|yes)\b" if raw else r"\b(false|no)\b", quote, re.I))
    if isinstance(raw, (int, float)) or (
        isinstance(raw, str) and re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", raw.strip())
    ):
        # Structured numeric output turns 12 into 12.0; compare complete numeric tokens.
        # Do not accept 12 inside 120, 12.5, a model code, or a negative quantity.
        numbers = re.findall(r"(?<![\w.+/-])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?![\w./+-])", quote)
        return any(Decimal(number) == Decimal(str(raw)) for number in numbers)
    return bool(re.search(r"(?<!\w)" + re.escape(str(raw).strip()) + r"(?!\w)", quote, re.I))


def grounded_quote(quote: str, passage: str) -> str | None:
    if not quote.strip():
        return None
    # PDF layout often adds spaces/newlines. Store the actual source slice, not a paraphrase.
    pattern = r"\s+".join(re.escape(token) for token in quote.split())
    trimmed = quote.strip()
    if trimmed[0].isalnum():
        pattern = (r"(?<![\w.+/-])" if trimmed[0].isdigit() else r"(?<!\w)") + pattern
    if trimmed[-1].isalnum():
        pattern += r"(?![\w./+-])" if trimmed[-1].isdigit() else r"(?!\w)"
    match = re.search(pattern, passage)
    return match.group(0) if match else None


def measurement_quote_supported(
    attribute: AttributeDefinition, quote: str, passage: str = ""
) -> bool:
    """Reject ambiguous measurement rows and product/packaging subject mismatches.

    This conservative check covers common measurement labels, not general semantic entailment.
    Unknown custom quantities still depend on the schema description and reviewer.
    """
    if attribute.type != "number" or attribute.unit not in {"mm", "cm", "m", "g", "kg"}:
        return True
    requested = " ".join([attribute.key.replace("_", " "), attribute.label, *attribute.aliases])
    dimensions = [
        r"\b(?:length|len|comprimento)\b",
        r"\b(?:width|wid|largura)\b",
        r"\b(?:height|hgt|altura)\b",
        r"\b(?:depth|profundidade)\b",
        r"\b(?:diameter|diâmetro)\b",
        r"\b(?:thickness|espessura)\b",
        r"\b(?:weight|mass|peso|massa)\b",
    ]
    labels = [pattern for pattern in dimensions if re.search(pattern, requested, re.I)]
    if not labels:
        return True
    if not any(re.search(pattern, quote, re.I) for pattern in labels):
        return False
    packaging = r"\b(?:carton|packaging|package|box|caixa|embalagem)\b"
    if not re.search(packaging, requested, re.I):
        if re.search(packaging, quote, re.I):
            return False
        # A quotation can omit the table title while retaining its column names.
        # Consult the source prefix so cropping "Carton Dimensions" cannot change subject.
        prefix = passage.partition(quote)[0] if quote in passage else ""
        packaging_header = packaging + r"\s+(?:dimensions?|measurements?|weight)\b"
        explicit_product = r"\b(?:product|glove|item|produto|luva)\s+(?:length|width|height|depth|diameter|thickness|weight|mass|comprimento|largura|altura|peso)\b"
        if re.search(packaging_header, prefix, re.I) and not re.search(
            explicit_product, quote, re.I
        ):
            return False
    return True


async def validate_values(state: EnrichState):
    await step(state, "Validating values and evidence")
    attributes = {a["key"]: AttributeDefinition.model_validate(a) for a in state["attributes"]}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    async with transaction() as db:
        for value in state["extracted"]:
            if (
                value["attribute_key"] not in attributes
                or value["chunk_id"] not in state["available"]
            ):
                continue
            chunk = await get_scoped(db, Chunk, value["chunk_id"], state["workspace_id"])
            doc = await get_scoped(db, SourceDocument, chunk.document_id, state["workspace_id"])
            basis = identity_match(state["identity"], chunk.identifiers)
            quote = grounded_quote(value["quote"], chunk.text)
            if (
                not basis["applies"]
                or not doc.active
                or not quote
                or not literal_value_supported(value["raw_value"], quote)
                or not measurement_quote_supported(
                    attributes[value["attribute_key"]], quote, chunk.text
                )
            ):
                continue
            validation = normalize(value["raw_value"], attributes[value["attribute_key"]])
            normalized = validation.normalized if validation.valid else value["raw_value"]
            fingerprint = hashlib.sha256(
                json.dumps(normalized, sort_keys=True).encode()
            ).hexdigest()
            key = (value["attribute_key"], fingerprint)
            evidence = {
                "chunk_id": chunk.id,
                "document_id": doc.id,
                "document_version": doc.version,
                "quote": quote,
                "location": chunk.location,
                "identity_basis": basis,
            }
            if key in grouped:
                if evidence not in grouped[key]["evidence"]:
                    grouped[key]["evidence"].append(evidence)
            else:
                grouped[key] = {
                    "attribute_key": value["attribute_key"],
                    "fingerprint": fingerprint,
                    "raw_value": value["raw_value"],
                    "normalized_value": validation.normalized,
                    "validation": validation.model_dump(),
                    "status": "supported" if validation.valid else "invalid",
                    "original_value": state["values"].get(value["attribute_key"]),
                    "conflict": {},
                    "evidence": [evidence],
                }
    candidates = list(grouped.values())
    for key in attributes:
        members = [c for c in candidates if c["attribute_key"] == key]
        valid = [c for c in members if c["validation"]["valid"]]
        if len(valid) > 1:
            for candidate in valid:
                candidate["status"] = "conflicting"
                candidate["conflict"] = {
                    "reason": "Sources disagree",
                    "alternatives": [c["normalized_value"] for c in valid],
                }
        for candidate in members:
            original = state["values"].get(key)
            if present(original):
                existing = normalize(original, attributes[key])
                if existing.normalized != candidate["normalized_value"]:
                    candidate["status"] = "needs_review"
                    candidate["conflict"] = {
                        "reason": "Evidence contradicts a populated field; original is preserved",
                        "original": original,
                    }
                else:
                    candidates.remove(candidate)
        if not members and not present(state["values"].get(key)):
            candidates.append(
                {
                    "attribute_key": key,
                    "fingerprint": "unknown",
                    "raw_value": None,
                    "normalized_value": None,
                    "original_value": None,
                    "status": "insufficient_evidence",
                    "validation": {
                        "valid": False,
                        "errors": [state.get("limitation") or "No explicit supporting value found"],
                        "notes": [],
                    },
                    "conflict": {},
                    "evidence": [],
                }
            )
    return {"candidates": candidates}


def route_after_validation(state: EnrichState):
    unresolved = any(
        c["status"] in {"insufficient_evidence", "conflicting"} for c in state["candidates"]
    )
    if unresolved and state["round"] < settings().max_retrieval_rounds:
        return "retrieve"
    return "persist"


async def persist_candidates(state: EnrichState):
    await step(state, "Preparing review")
    async with transaction() as db:
        run = await get_scoped(db, ProductRun, state["run_id"], state["workspace_id"], lock=True)
        for data in state["candidates"]:
            existing = await db.scalar(
                select(Candidate).where(
                    Candidate.workspace_id == state["workspace_id"],
                    Candidate.run_id == run.id,
                    Candidate.attribute_key == data["attribute_key"],
                    Candidate.fingerprint == data["fingerprint"],
                )
            )
            if existing:
                continue
            candidate = Candidate(
                workspace_id=state["workspace_id"],
                run_id=run.id,
                product_id=run.product_id,
                **{k: v for k, v in data.items() if k != "evidence"},
            )
            db.add(candidate)
            await db.flush()
            for evidence in data["evidence"]:
                db.add(
                    Evidence(
                        workspace_id=state["workspace_id"], candidate_id=candidate.id, **evidence
                    )
                )
        run.metrics = {
            **state["metrics"],
            "latency_seconds": round(time.time() - state["started"], 3),
        }
        pending = len(state["candidates"])
    return {"pending": pending}


def review_gate(state: EnrichState):
    decision = interrupt(
        {
            "run_id": state["run_id"],
            "pending_fields": state["pending"],
            "message": "Review proposed values and evidence",
        }
    )
    return {"review_id": decision["review_id"]}


async def apply_review(state: EnrichState):
    await step(state, "Applying approved changes")
    async with transaction() as db:
        workspace = await get_workspace_lock(db, state["workspace_id"])
        run = await get_scoped(db, ProductRun, state["run_id"], state["workspace_id"], lock=True)
        review = await get_scoped(db, Review, state["review_id"], state["workspace_id"], lock=True)
        product = await get_scoped(db, Product, run.product_id, state["workspace_id"], lock=True)
        candidates = (
            await db.scalars(
                select(Candidate)
                .where(Candidate.workspace_id == state["workspace_id"], Candidate.run_id == run.id)
                .with_for_update()
            )
        ).all()
        if review.status == "applied":
            return {"pending": sum(c.status not in {"approved", "rejected"} for c in candidates)}
        if run.cancelled:
            raise ValueError("Run cancelled before the review could be applied")
        membership = await db.get(Membership, (state["workspace_id"], review.actor_id))
        if not membership or membership.role not in {"owner", "reviewer"}:
            raise ValueError("Reviewer no longer has approval permission")
        schema = await current_schema(db, state["workspace_id"], product.category_id)
        if review.run_id != run.id or review.interrupt_id != run.interrupt_id:
            raise ValueError("Review does not target this workflow interrupt")
        if (
            schema.id != run.schema_id
            or workspace.source_revision != run.source_revision
            or product.revision != review.product_revision
        ):
            raise ValueError(
                "Stale review: source, schema or product changed. Revalidate before applying."
            )
        definitions = {
            a.key: a for a in CategoryDefinition.model_validate(schema.definition).attributes
        }
        by_id = {c.id: c for c in candidates}
        approved = dict(product.approved)
        changed = False
        for decision in review.decisions:
            candidate = by_id.get(decision["candidate_id"])
            if candidate and candidate.status == "rejected" and decision["action"] == "reject":
                continue
            if (
                not candidate
                or candidate.version != decision["version"]
                or candidate.status in {"approved", "rejected"}
            ):
                raise ValueError("Proposal changed since review submission")
            if decision["action"] == "reject":
                candidate.status = "rejected"
                continue
            if present(product.attributes.get(candidate.attribute_key)) or present(
                approved.get(candidate.attribute_key)
            ):
                raise ValueError("Approval cannot overwrite a populated field")
            manual = decision["action"] == "edit"
            if not manual:
                evidence = (
                    await db.scalars(
                        select(Evidence).where(
                            Evidence.workspace_id == state["workspace_id"],
                            Evidence.candidate_id == candidate.id,
                        )
                    )
                ).all()
                if not evidence or candidate.status not in {
                    "supported",
                    "conflicting",
                    "needs_review",
                }:
                    raise ValueError("Source-backed approval needs valid evidence")
                for link in evidence:
                    chunk = await get_scoped(db, Chunk, link.chunk_id, state["workspace_id"])
                    doc = await get_scoped(
                        db, SourceDocument, link.document_id, state["workspace_id"]
                    )
                    if (
                        chunk.id not in run.available_chunks
                        or chunk.document_id != doc.id
                        or not doc.active
                        or doc.version != link.document_version
                        or link.quote not in chunk.text
                    ):
                        raise ValueError("Source evidence changed; revalidate the proposal")
            raw = decision["value"] if manual else candidate.normalized_value
            validation = normalize(raw, definitions[candidate.attribute_key])
            if not validation.valid:
                raise ValueError(
                    "Reviewed value failed validation: " + "; ".join(validation.errors)
                )
            candidate.normalized_value = validation.normalized
            candidate.manual = manual
            candidate.status = "approved"
            approved[candidate.attribute_key] = validation.normalized
            changed = True
            for alternative in candidates:
                if (
                    alternative.id != candidate.id
                    and alternative.attribute_key == candidate.attribute_key
                ):
                    alternative.status = "rejected"
                    alternative.conflict = {
                        **alternative.conflict,
                        "resolution": "Alternative value approved",
                        "review_id": review.id,
                    }
        if changed:
            product.approved = approved
            product.revision += 1
            run.product_revision = product.revision
            db.add(
                ProductRevision(
                    workspace_id=state["workspace_id"],
                    product_id=product.id,
                    revision=product.revision,
                    values=approved,
                    actor_id=review.actor_id,
                )
            )
        review.status = "applied"
        db.add(
            AuditEvent(
                workspace_id=state["workspace_id"],
                actor_id=review.actor_id,
                action="review.applied",
                entity_id=review.id,
                details={"product_revision": product.revision, "decisions": review.decisions},
            )
        )
        pending = sum(c.status not in {"approved", "rejected"} for c in candidates)
        return {"pending": pending}


async def refresh_product(state: EnrichState):
    await step(state, "Refreshing catalog")
    async with transaction() as db:
        run = await get_scoped(db, ProductRun, state["run_id"], state["workspace_id"], lock=True)
        if run.cancelled:
            raise ValueError("Run cancelled before completion")
        product = await get_scoped(db, Product, run.product_id, state["workspace_id"])
        product.search_text = " ".join(
            [
                product.sku,
                product.name,
                product.manufacturer,
                product.model,
                product.mpn,
                *map(str, {**product.attributes, **product.approved}.values()),
            ]
        )
        run.status = "completed"
        run.step = "Completed"
        db.add(
            WorkflowEvent(
                workspace_id=state["workspace_id"],
                run_id=run.id,
                step="Workflow completed",
                details={"product_revision": product.revision},
            )
        )
        run.interrupt_id = None
        run.error = None
    return {}


def enrichment_graph(checkpointer):
    graph = StateGraph(EnrichState)
    for name, node in [
        ("inspect", inspect_product),
        ("retrieve", retrieve),
        ("identity", check_identity),
        ("extract", extract_values),
        ("validate", validate_values),
        ("persist", persist_candidates),
        ("review", review_gate),
        ("apply", apply_review),
        ("refresh", refresh_product),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "inspect")
    for first, second in [
        ("inspect", "retrieve"),
        ("retrieve", "identity"),
        ("identity", "extract"),
        ("extract", "validate"),
        ("review", "apply"),
        ("refresh", END),
    ]:
        graph.add_edge(first, second)
    graph.add_conditional_edges("validate", route_after_validation, ["retrieve", "persist"])
    graph.add_conditional_edges(
        "persist", lambda s: "review" if s["pending"] else "refresh", ["review", "refresh"]
    )
    graph.add_conditional_edges(
        "apply", lambda s: "review" if s["pending"] else "refresh", ["review", "refresh"]
    )
    return graph.compile(checkpointer=checkpointer)
