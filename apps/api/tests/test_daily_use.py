import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from catalogforge.worker import queue, recover_stalled
from conftest import SYNC_ENGINE, checked, review_body, start_run, wait_for
from procrastinate.jobs import Status
from sqlalchemy import text


def test_two_reviewers_racing_apply_only_one_revision(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0021", ["material"])
    candidate = detail["candidates"][0]
    first = review_body(
        detail, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
    )
    second = {**first, "idempotency_key": str(uuid4())}
    path = "/runs/" + detail["run"]["id"] + "/review"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda body: ws["client"].post(path, json=body), [first, second]))
    assert sorted(r.status_code for r in results) == [200, 409]
    review = next(r.json() for r in results if r.status_code == 200)
    wait_for(ws["client"], "/review-decisions/" + review["id"], "applied")
    final = wait_for(ws["client"], "/runs/" + detail["run"]["id"], "completed")
    assert final["product"]["revision"] == 2
    with SYNC_ENGINE.connect() as db:
        priority = db.scalar(
            text(
                "SELECT priority FROM procrastinate_jobs WHERE args->>'entity_id'=:id AND args->>'kind'='resume'"
            ),
            {"id": detail["run"]["id"]},
        )
    assert priority > 0
    with SYNC_ENGINE.connect() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE entity_id=:id AND action='review.applied'"
                ),
                {"id": review["id"]},
            )
            == 1
        )


def test_concurrent_duplicate_submission_has_one_decision(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0022", ["material"])
    candidate = detail["candidates"][0]
    body = review_body(
        detail, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: checked(
                    ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body)
                ),
                range(2),
            )
        )
    assert results[0]["id"] == results[1]["id"]
    wait_for(ws["client"], "/review-decisions/" + results[0]["id"], "applied")


def test_revalidation_racing_approval_does_not_deadlock(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0023", ["material"])
    candidate = detail["candidates"][0]
    body = review_body(
        detail, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
    )
    prefix = "/runs/" + detail["run"]["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        approval = pool.submit(ws["client"].post, prefix + "/review", json=body)
        replacement = pool.submit(ws["client"].post, prefix + "/revalidate")
        assert approval.result(timeout=15).status_code in {200, 409}
        new = checked(replacement.result(timeout=15))
    wait_for(ws["client"], "/runs/" + new["runs"][0]["id"])
    final = checked(ws["client"].get(prefix))
    assert final["run"]["status"] == "cancelled"


@pytest.mark.parametrize(
    "attempts,initial", [(2, "processing"), (3, "processing"), (3, "waiting_review")]
)
async def test_stalled_attempt_budget_has_a_terminal_outcome(
    workspace, monkeypatch, attempts, initial
):
    ws = workspace
    detail = await asyncio.to_thread(
        start_run,
        ws,
        {
            (2, "processing"): "CF-0024",
            (3, "processing"): "CF-0025",
            (3, "waiting_review"): "CF-0026",
        }[(attempts, initial)],
        ["material"],
    )
    # The real enrichment job is complete at its interrupt. Model a dead worker's queue delivery.
    with SYNC_ENGINE.begin() as db:
        db.execute(
            text("UPDATE product_runs SET status=:status WHERE id=:id"),
            {"status": initial, "id": detail["run"]["id"]},
        )
    job = SimpleNamespace(
        id=999999,
        attempts=attempts,
        task_kwargs={
            "workspace_id": ws["id"],
            "kind": "enrich",
            "entity_id": detail["run"]["id"],
            "payload": {},
        },
    )
    retry, finish = AsyncMock(), AsyncMock()
    monkeypatch.setattr(queue.job_manager, "get_stalled_jobs", AsyncMock(return_value=[job]))
    monkeypatch.setattr(queue.job_manager, "retry_job", retry)
    monkeypatch.setattr(queue.job_manager, "finish_job", finish)
    await recover_stalled()
    final = checked(ws["client"].get("/runs/" + detail["run"]["id"]))
    if attempts < 3:
        retry.assert_awaited_once_with(job)
        finish.assert_not_awaited()
    elif initial == "waiting_review":
        finish.assert_awaited_once_with(job, Status.SUCCEEDED, delete_job=False)
        assert final["run"]["status"] == initial
    else:
        finish.assert_awaited_once_with(job, Status.FAILED, delete_job=False)
        assert final["run"]["status"] == "failed" and "exhausted" in final["run"]["error"]
    checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/cancel"))


def test_example_install_is_additive_idempotent_and_authorized(workspace):
    from catalogforge.models import Base, Workspace
    from sqlalchemy import delete

    ws = workspace
    assert ws["viewer"].post("/examples/install").status_code == 403
    before = checked(ws["client"].get("/products"))
    result = checked(ws["client"].post("/examples/install"))
    wid = result["workspace_id"]
    try:
        again = checked(ws["client"].post("/examples/install"))
        assert again["workspace_id"] == wid and len(result["cases"]) == 12
        assert checked(ws["client"].get("/products")) == before
        assert ws["client"].post("/examples/NS-001/run").status_code == 409
        ws["client"].headers["x-workspace-id"] = wid
        assert len(checked(ws["client"].get("/products"))) == 12
        import time

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = checked(ws["client"].get("/examples"))
            if state["sources_ready"] == 5:
                break
            time.sleep(0.2)
        assert state["sources_ready"] == 5
        run = checked(ws["client"].post("/examples/NS-001/run"))
        same = checked(ws["client"].post("/examples/NS-001/run"))
        assert run["id"] == same["id"]
        final = wait_for(ws["client"], "/runs/" + run["id"])
        assert all(c["status"] == "supported" for c in final["candidates"])
        assert ws["client"].get("/examples/files/private.env").status_code == 404
    finally:
        ws["client"].headers["x-workspace-id"] = ws["id"]
        with SYNC_ENGINE.begin() as db:
            db.execute(
                text("DELETE FROM procrastinate_jobs WHERE args->>'workspace_id'=:id"), {"id": wid}
            )
            for table in reversed(Base.metadata.sorted_tables):
                if "workspace_id" in table.c:
                    db.execute(delete(table).where(table.c.workspace_id == wid))
            for name in ["checkpoint_writes", "checkpoint_blobs", "checkpoints"]:
                db.execute(
                    text(f"DELETE FROM checkpoints.{name} WHERE thread_id LIKE :prefix"),
                    {"prefix": wid + ":%"},
                )
            db.execute(delete(Workspace).where(Workspace.id == wid))


async def test_commit_failure_returns_error_instead_of_success():
    import httpx
    from catalogforge.db import session_dependency
    from catalogforge.main import app
    from sqlalchemy.exc import IntegrityError

    async def failed_commit():
        yield SimpleNamespace(execute=AsyncMock())
        raise IntegrityError("COMMIT", {}, Exception("deferred constraint failure"))

    app.dependency_overrides[session_dependency] = failed_commit
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get("/api/health")
        assert response.status_code == 409
        assert "concurrent change" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(session_dependency, None)


def test_revalidation_preserves_completed_history(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0027", ["material"])
    candidate = detail["candidates"][0]
    body = review_body(
        detail, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
    )
    review = checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body))
    wait_for(ws["client"], "/review-decisions/" + review["id"], "applied")
    wait_for(ws["client"], "/runs/" + detail["run"]["id"], "completed")
    replacement = checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/revalidate"))
    previous = checked(ws["client"].get("/runs/" + detail["run"]["id"]))
    assert previous["run"]["status"] == "completed"
    with SYNC_ENGINE.connect() as db:
        assert (
            db.scalar(
                text("SELECT cancelled FROM product_runs WHERE id=:id"),
                {"id": detail["run"]["id"]},
            )
            is False
        )
    wait_for(ws["client"], "/runs/" + replacement["runs"][0]["id"])
