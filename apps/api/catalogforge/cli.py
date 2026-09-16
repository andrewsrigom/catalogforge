import argparse
import asyncio
import json
import subprocess
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from .auth import Principal, hasher
from .config import settings
from .contracts import CategoryDefinition, ImportMapping
from .db import transaction
from .models import Membership, SourceDocument, User, Workspace, uid
from .services import (
    categories,
    confirm_import,
    enqueue,
    get_workspace_lock,
    preview_import,
    save_schema,
    upload_source,
)
from .worker import checkpoint_connection, queue

DEMO_WORKSPACE = "00000000-0000-0000-0000-000000000001"


async def infrastructure():
    async with await psycopg.AsyncConnection.connect(
        settings().pg_url, autocommit=True
    ) as connection:
        await connection.execute("CREATE SCHEMA IF NOT EXISTS checkpoints")
    async with AsyncPostgresSaver.from_conn_string(checkpoint_connection()) as saver:
        await saver.setup()
    async with queue.open_async():
        async with await psycopg.AsyncConnection.connect(
            settings().pg_url, autocommit=True
        ) as connection:
            await connection.execute(
                "SELECT pg_advisory_lock(hashtext('catalogforge.queue_schema'))"
            )
            try:
                cursor = await connection.execute("SELECT to_regclass('public.procrastinate_jobs')")
                row = await cursor.fetchone()
                if not row or row[0] is None:
                    await queue.schema_manager.apply_schema_async()
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(hashtext('catalogforge.queue_schema'))"
                )


async def seed():
    async with transaction() as db:
        workspace = await db.get(Workspace, DEMO_WORKSPACE)
        if not workspace:
            workspace = Workspace(id=DEMO_WORKSPACE, name="ForgeWorks · Synthetic demo")
            db.add(workspace)
            await db.flush()
        user = None
        for email, name, role in [
            ("reviewer@catalogforge.local", "Alex Morgan", "reviewer"),
            ("viewer@catalogforge.local", "Sam Rivera", "viewer"),
        ]:
            existing = await db.scalar(select(User).where(User.email == email))
            if not existing:
                existing = User(
                    id=uid(),
                    email=email,
                    name=name,
                    password_hash=hasher.hash(settings().demo_password),
                )
                db.add(existing)
                await db.flush()
            if not await db.get(Membership, (workspace.id, existing.id)):
                db.add(Membership(workspace_id=workspace.id, user_id=existing.id, role=role))
            if role == "reviewer":
                user = existing
        await db.flush()
        assert user is not None
        actor = Principal(user=user, session=None, workspace_id=workspace.id, role="reviewer")
        schema_list = await categories(db, workspace.id)
        if schema_list:
            category_id = schema_list[0].id
        else:
            category = await save_schema(
                db,
                actor,
                CategoryDefinition.model_validate_json(Path("fixtures/category.json").read_text()),
            )
            category_id = category.id
        imported = await preview_import(
            db, actor, "catalog.csv", Path("fixtures/catalog.csv").read_bytes()
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
        await confirm_import(
            db, actor, imported.id, ImportMapping(category_id=category_id, mapping=mapping)
        )
        for path in sorted(Path("fixtures/sources").iterdir()):
            await upload_source(db, actor, path.name, path.read_bytes())
    print(
        "Seeded synthetic workspace. reviewer@catalogforge.local / password from DEMO_PASSWORD (.env.example default)."
    )


async def reindex():
    async with transaction() as db:
        workspaces = (await db.scalars(select(Workspace))).all()
        for workspace in workspaces:
            await get_workspace_lock(db, workspace.id)
            docs = (
                await db.scalars(
                    select(SourceDocument).where(
                        SourceDocument.workspace_id == workspace.id, SourceDocument.active.is_(True)
                    )
                )
            ).all()
            for doc in docs:
                doc.status = "queued"
                # Existing chunks remain as immutable evidence; vectors are replaced by ordinal.
                await enqueue(db, workspace.id, "ingest", doc.id, f"reindex:{doc.id}:{uid()}")
                async with AsyncPostgresSaver.from_conn_string(checkpoint_connection()) as saver:
                    await saver.adelete_thread(f"{workspace.id}:document:{doc.id}")
            workspace.source_revision += 1
    print("Reindex requested. Existing proposals require revalidation.")


def initialize():
    # Extensions/sequences are also in the initial migration so fresh Alembic installs are complete.
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    asyncio.run(infrastructure())
    asyncio.run(seed())


async def seed_pilot():
    from uuid import NAMESPACE_URL, uuid5

    workspace_id = str(uuid5(NAMESPACE_URL, "catalogforge:isolated-pilot:v1"))
    async with transaction() as db:
        if not await db.get(Workspace, workspace_id):
            db.add(Workspace(id=workspace_id, name="AI pilot · isolated evaluation"))
            await db.flush()
        user = await db.scalar(select(User).where(User.email == "pilot@catalogforge.local"))
        if user is None:
            user = User(
                id=uid(),
                email="pilot@catalogforge.local",
                name="Pilot Reviewer",
                password_hash=hasher.hash(settings().demo_password),
            )
            db.add(user)
            await db.flush()
        if not await db.get(Membership, (workspace_id, user.id)):
            db.add(Membership(workspace_id=workspace_id, user_id=user.id, role="reviewer"))
    print("Initialized an empty isolated pilot; no documents or provider jobs were created.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["init", "init-pilot", "seed", "reindex", "openapi", "demo-reset"]
    )
    args = parser.parse_args()
    if args.command == "init-pilot":
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        asyncio.run(infrastructure())
        asyncio.run(seed_pilot())
    elif args.command == "init":
        initialize()
    elif args.command == "seed":
        asyncio.run(seed())
    elif args.command == "demo-reset":
        from .maintenance import reset_demo

        reset_demo()
    elif args.command == "reindex":
        asyncio.run(reindex())
    else:
        from .main import app

        Path("apps/web/src/api").mkdir(parents=True, exist_ok=True)
        Path("apps/web/openapi.json").write_text(json.dumps(app.openapi(), indent=2))


if __name__ == "__main__":
    main()
