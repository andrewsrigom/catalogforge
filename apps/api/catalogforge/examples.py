"""An additive, per-user synthetic workspace; all work uses the normal services and graphs."""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select, text

from . import services
from .auth import Principal
from .config import settings
from .contracts import BatchInput, CategoryDefinition, ImportMapping
from .models import Membership, Product, ProductRun, SourceDocument, Workspace

ROOT = Path("fixtures/workday")


def manifest():
    return json.loads((ROOT / "manifest.json").read_text())


def workspace_id(user_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, "catalogforge:examples:northstar-v1:" + user_id))


async def collection(db, actor):
    content = manifest()
    wid = workspace_id(actor.user.id)
    member = await db.get(Membership, (wid, actor.user.id))
    products, runs, docs = [], [], []
    if member:
        products = (await db.scalars(select(Product).where(Product.workspace_id == wid))).all()
        runs = (
            await db.scalars(
                select(ProductRun)
                .where(ProductRun.workspace_id == wid)
                .order_by(ProductRun.created_at.desc())
            )
        ).all()
        docs = (
            await db.scalars(
                select(SourceDocument).where(
                    SourceDocument.workspace_id == wid, SourceDocument.active.is_(True)
                )
            )
        ).all()
    cases = []
    for case in content["cases"]:
        product = next((p for p in products if p.sku == case["sku"]), None)
        run = next((item for item in runs if product and item.product_id == product.id), None)
        cases.append(
            {
                **case,
                "product_id": product.id if product else None,
                "run_id": run.id if run else None,
                "status": run.status if run else "not_started",
            }
        )
    return {
        **content,
        "cases": cases,
        "workspace_id": wid if member else None,
        "sources_ready": sum(d.status == "ready" for d in docs),
        "sources_total": len(content["sources"]),
        "mode": settings().ai_mode,
    }


async def install(db, actor):
    if settings().ai_mode != "fixture":
        raise HTTPException(
            409, "Guided examples require fixture mode so no paid model calls are made"
        )
    wid = workspace_id(actor.user.id)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "examples:" + wid}
    )
    existing = await db.get(Workspace, wid)
    if existing:
        if not await db.get(Membership, (wid, actor.user.id)):
            raise HTTPException(403, "Example workspace membership is no longer available")
        return await collection(db, actor)
    db.add(Workspace(id=wid, name="Northstar · Guided examples"))
    await db.flush()
    db.add(Membership(workspace_id=wid, user_id=actor.user.id, role="owner"))
    await db.flush()
    scoped = Principal(user=actor.user, session=actor.session, workspace_id=wid, role="owner")
    category = await services.save_schema(
        db, scoped, CategoryDefinition.model_validate_json((ROOT / "category.json").read_text())
    )
    imported = await services.preview_import(
        db, scoped, "northstar-catalog.csv", (ROOT / "catalog.csv").read_bytes()
    )
    mapping = {
        "sku": "SKU",
        "name": "Product name",
        "manufacturer": "Manufacturer",
        "model": "Model",
        "mpn": "MPN",
        "size": "Size",
        "coating": "Coating",
        "material": "Material",
        "length_mm": "Length",
        "pack_quantity": "Pairs per pack",
        "cut_level": "Cut rating",
        "touchscreen": "Touchscreen",
        "certification": "Certification",
    }
    await services.confirm_import(
        db, scoped, imported.id, ImportMapping(category_id=category.id, mapping=mapping)
    )
    for filename in manifest()["sources"]:
        await services.upload_source(
            db, scoped, filename, (ROOT / "sources" / filename).read_bytes()
        )
    return await collection(db, actor)


async def start(db, actor, sku):
    if settings().ai_mode != "fixture":
        raise HTTPException(409, "Switch to fixture mode to run the guided examples")
    wid = workspace_id(actor.user.id)
    if actor.workspace_id != wid:
        raise HTTPException(409, "Open your guided example workspace before starting a case")
    await services.get_workspace_lock(db, wid)
    content = await collection(db, actor)
    case = next((c for c in content["cases"] if c["sku"] == sku), None)
    if not case or not case["product_id"]:
        raise HTTPException(404, "Example product not found")
    if case["run_id"]:
        return await services.get_scoped(db, ProductRun, case["run_id"], wid)
    if content["sources_ready"] != content["sources_total"]:
        raise HTTPException(409, "Wait until all five example source documents are ready")
    batch = await services.start_batch(
        db,
        actor,
        BatchInput(
            product_ids=[case["product_id"]],
            attributes=case["attributes"],
            title=case["sku"] + " · " + case["title"],
        ),
    )
    return await db.scalar(
        select(ProductRun).where(ProductRun.workspace_id == wid, ProductRun.batch_id == batch.id)
    )
