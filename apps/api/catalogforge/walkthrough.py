"""A persistent, isolated walkthrough using the normal ingestion and review services."""

import csv
import io
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


def workspace_id(user_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, "catalogforge:walkthrough:v1:" + user_id))


async def state(db, actor):
    wid = workspace_id(actor.user.id)
    member = await db.get(Membership, (wid, actor.user.id))
    product, run, sources = None, None, []
    if member:
        row = await db.scalar(
            select(Product).where(Product.workspace_id == wid, Product.sku == "NS-001")
        )
        if row:
            schema = await services.current_schema(db, wid, row.category_id)
            product = services.product_view(row, schema)
            latest = await db.scalar(
                select(ProductRun)
                .where(ProductRun.workspace_id == wid, ProductRun.product_id == row.id)
                .order_by(ProductRun.created_at.desc())
                .limit(1)
            )
            if latest:
                run = await services.run_view(db, latest)
        sources = (
            await db.scalars(
                select(SourceDocument)
                .where(SourceDocument.workspace_id == wid)
                .order_by(SourceDocument.filename)
            )
        ).all()
    return {
        "workspace_id": wid if member else None,
        "product": product,
        "run": run,
        "sources": sources,
        "mode": settings().ai_mode,
    }


async def install(db, actor):
    if settings().ai_mode != "fixture":
        raise HTTPException(409, "The walkthrough requires fixture mode")
    wid = workspace_id(actor.user.id)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "walkthrough:" + wid}
    )
    if await db.get(Workspace, wid):
        if not await db.get(Membership, (wid, actor.user.id)):
            raise HTTPException(403, "Walkthrough workspace membership is no longer available")
        return await state(db, actor)
    db.add(Workspace(id=wid, name="Northstar · Guided walkthrough"))
    await db.flush()
    db.add(Membership(workspace_id=wid, user_id=actor.user.id, role="owner"))
    await db.flush()
    scoped = Principal(user=actor.user, session=actor.session, workspace_id=wid, role="owner")
    category = await services.save_schema(
        db, scoped, CategoryDefinition.model_validate_json((ROOT / "category.json").read_text())
    )
    records = list(csv.DictReader(io.StringIO((ROOT / "catalog.csv").read_text())))
    record = next(row for row in records if row["SKU"] == "NS-001")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(record))
    writer.writeheader()
    writer.writerow(record)
    imported = await services.preview_import(
        db, scoped, "walkthrough-catalog.csv", output.getvalue().encode()
    )
    await services.confirm_import(
        db,
        scoped,
        imported.id,
        ImportMapping(
            category_id=category.id,
            mapping={
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
            },
        ),
    )
    await services.upload_source(
        db,
        scoped,
        "01-northstar-datasheets.pdf",
        (ROOT / "sources/01-northstar-datasheets.pdf").read_bytes(),
    )
    await services.upload_source(
        db,
        scoped,
        "02-alternate-supplier.csv",
        Path("fixtures/walkthrough/02-alternate-supplier.csv").read_bytes(),
    )
    return await state(db, actor)


async def start(db, actor):
    wid = workspace_id(actor.user.id)
    if settings().ai_mode != "fixture" or actor.workspace_id != wid:
        raise HTTPException(409, "Open your walkthrough workspace in fixture mode first")
    await services.get_workspace_lock(db, wid)
    current = await state(db, actor)
    if current["run"]:
        return current["run"]
    if (
        not current["product"]
        or len(current["sources"]) != 2
        or any(doc.status != "ready" for doc in current["sources"])
    ):
        raise HTTPException(409, "Wait until both walkthrough sources are ready")
    batch = await services.start_batch(
        db,
        actor,
        BatchInput(
            product_ids=[current["product"].id],
            attributes=["material", "length_mm", "pack_quantity"],
            title="Guided walkthrough · compare, verify, decide",
        ),
    )
    run = await db.scalar(
        select(ProductRun).where(ProductRun.workspace_id == wid, ProductRun.batch_id == batch.id)
    )
    return await services.run_view(db, run)
