import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from catalogforge.auth import hasher
from catalogforge.config import settings
from catalogforge.models import Base, Membership, User, Workspace
from catalogforge.walkthrough import workspace_id as walkthrough_workspace_id
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
SYNC_ENGINE = create_engine(settings().database_url)


def checked(response):
    assert not response.is_error, (
        f"{response.request.method} {response.request.url}: {response.status_code} {response.text}"
    )
    return response.json() if response.content else None


def wait_for(client, path, expected="waiting_review", timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = checked(client.get(path))
        status = data["run"]["status"] if "run" in data else data["status"]
        if status == expected:
            return data
        if status == "failed" and expected != "failed":
            raise AssertionError(data)
        time.sleep(0.15)
    raise AssertionError(f"Timed out on {path}: {data}")


@pytest.fixture(scope="module")
def workspace():
    workspace_id, user_id, viewer_id, other_id = [str(uuid4()) for _ in range(4)]
    password = "integration-test-password"
    email = f"{user_id}@test.catalogforge.local"
    with Session(SYNC_ENGINE) as db, db.begin():
        db.add_all(
            [
                Workspace(id=workspace_id, name="Integration test"),
                Workspace(id=other_id, name="Other isolated workspace"),
            ]
        )
        db.add_all(
            [
                User(
                    id=user_id,
                    email=email,
                    name="Test Reviewer",
                    password_hash=hasher.hash(password),
                ),
                User(
                    id=viewer_id,
                    email=f"{viewer_id}@test.catalogforge.local",
                    name="Test Viewer",
                    password_hash=hasher.hash(password),
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                Membership(workspace_id=workspace_id, user_id=user_id, role="reviewer"),
                Membership(workspace_id=other_id, user_id=user_id, role="reviewer"),
                Membership(workspace_id=workspace_id, user_id=viewer_id, role="viewer"),
            ]
        )
    client = httpx.Client(
        base_url=os.getenv("TEST_API_URL", "http://127.0.0.1:8188/api"), timeout=30
    )
    login = checked(client.post("/auth/login", json={"email": email, "password": password}))
    client.headers.update({"x-workspace-id": workspace_id, "x-csrf-token": login["csrf"]})
    viewer = httpx.Client(base_url=client.base_url, timeout=30)
    login_viewer = checked(
        viewer.post(
            "/auth/login",
            json={"email": f"{viewer_id}@test.catalogforge.local", "password": password},
        )
    )
    viewer.headers.update({"x-workspace-id": workspace_id, "x-csrf-token": login_viewer["csrf"]})
    category = checked(
        client.post("/categories", json=json.loads((ROOT / "fixtures/category.json").read_text()))
    )
    preview = checked(
        client.post(
            "/imports/preview",
            files={"file": ("catalog.csv", (ROOT / "fixtures/catalog.csv").read_bytes())},
        )
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
    checked(
        client.post(
            f"/imports/{preview['id']}/confirm",
            json={"category_id": category["id"], "mapping": mapping},
        )
    )
    docs = []
    for path in sorted((ROOT / "fixtures/sources").iterdir()):
        document = checked(client.post("/sources", files={"file": (path.name, path.read_bytes())}))
        docs.append(document)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        ready = checked(client.get("/sources"))
        if all(doc["status"] == "ready" for doc in ready):
            break
        time.sleep(0.2)
    assert all(doc["status"] == "ready" for doc in ready), ready
    products = {p["sku"]: p for p in checked(client.get("/products"))}
    yield {
        "id": workspace_id,
        "other_id": other_id,
        "client": client,
        "viewer": viewer,
        "category": category,
        "products": products,
        "docs": docs,
        "preview": preview,
        "mapping": mapping,
    }
    client.close()
    viewer.close()
    # Only test-owned rows are removed. Running-job tests wait for settlement before teardown.
    with SYNC_ENGINE.begin() as connection:
        for wid in [workspace_id, other_id, walkthrough_workspace_id(user_id)]:
            connection.execute(
                text("DELETE FROM procrastinate_jobs WHERE args->>'workspace_id'=:wid"),
                {"wid": wid},
            )
            for table in reversed(Base.metadata.sorted_tables):
                if "workspace_id" in table.c:
                    connection.execute(delete(table).where(table.c.workspace_id == wid))
            for table in ["checkpoint_writes", "checkpoint_blobs", "checkpoints"]:
                connection.execute(
                    text(f"DELETE FROM checkpoints.{table} WHERE thread_id LIKE :prefix"),
                    {"prefix": wid + ":%"},
                )
            connection.execute(delete(Workspace).where(Workspace.id == wid))
        connection.execute(
            text("DELETE FROM auth_sessions WHERE user_id IN (:u,:v)"),
            {"u": user_id, "v": viewer_id},
        )
        connection.execute(delete(User).where(User.id.in_([user_id, viewer_id])))


def start_run(ws, sku, attributes=None):
    batch = checked(
        ws["client"].post(
            "/batches",
            json={"product_ids": [ws["products"][sku]["id"]], "attributes": attributes or []},
        )
    )
    return wait_for(ws["client"], "/runs/" + batch["runs"][0]["id"])


def review_body(detail, decisions, key=None):
    return {
        "interrupt_id": detail["run"]["interrupt_id"],
        "product_revision": detail["product"]["revision"],
        "idempotency_key": key or str(uuid4()),
        "decisions": decisions,
    }
