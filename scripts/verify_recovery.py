"""Kill only CatalogForge's worker while a review is blocked mid-transaction, then verify recovery."""

import json
import subprocess
import sys
import time
from pathlib import Path

from catalogforge.config import settings
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/tests"))
from conftest import SYNC_ENGINE, checked, review_body, start_run, wait_for, workspace  # noqa: E402


def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True)


def main():
    if settings().ai_mode != "fixture":
        raise SystemExit(
            "This verification requires AI_MODE=fixture; real-provider calls are not part of this test"
        )
    context = workspace.__wrapped__()
    ws = next(context)
    try:
        detail = start_run(ws, "CF-0031", ["material"])
        candidate = detail["candidates"][0]
        # Do not interrupt unrelated active work before starting the isolated failure test.
        for _ in range(120):
            with SYNC_ENGINE.connect() as db:
                active = db.scalar(
                    text("SELECT count(*) FROM procrastinate_jobs WHERE status='doing'")
                )
            if active == 0:
                break
            time.sleep(0.25)
        assert active == 0, "Wait for existing jobs to settle before the recovery test"
        compose("stop", "worker")
        body = review_body(
            detail, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
        )
        review = checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body))
        with SYNC_ENGINE.connect() as blocker:
            txn = blocker.begin()
            blocker.execute(
                text("SELECT id FROM products WHERE id=:id FOR UPDATE"),
                {"id": detail["product"]["id"]},
            )
            compose("up", "-d", "--no-deps", "worker")
            for _ in range(120):
                state = checked(ws["client"].get("/runs/" + detail["run"]["id"]))
                if state["run"]["step"] == "Applying approved changes":
                    break
                time.sleep(0.25)
            assert state["run"]["step"] == "Applying approved changes", state
            compose("kill", "-s", "SIGKILL", "worker")
            txn.rollback()
        stopped = checked(ws["client"].get("/products/" + detail["product"]["id"]))
        assert stopped["revision"] == 1 and not stopped["approved"]
        started = time.perf_counter()
        compose("up", "-d", "--no-deps", "worker")
        final = wait_for(ws["client"], "/runs/" + detail["run"]["id"], "completed", timeout=100)
        applied = checked(ws["client"].get("/review-decisions/" + review["id"]))
        assert applied["status"] == "applied" and final["product"]["revision"] == 2
        assert final["candidates"][0]["id"] == candidate["id"]
        with SYNC_ENGINE.connect() as db:
            applied_count = db.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE action='review.applied' AND entity_id=:id"
                ),
                {"id": review["id"]},
            )
            job = db.execute(
                text(
                    "SELECT status,attempts FROM procrastinate_jobs WHERE args->>'entity_id'=:id AND args->>'kind'='resume'"
                ),
                {"id": detail["run"]["id"]},
            ).one()
        assert applied_count == 1 and job.attempts == 2, (applied_count, job)
        result = {
            "status": "passed",
            "signal": "SIGKILL",
            "blocked_step": "Applying approved changes",
            "checkpoint_and_candidate_preserved": True,
            "approved_once": True,
            "product_revision": final["product"]["revision"],
            "queue_attempts": job.attempts,
            "recovery_seconds": round(time.perf_counter() - started, 2),
        }
        (ROOT / ".local/abrupt-recovery.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        compose("up", "-d", "--no-deps", "worker")
        try:
            next(context)
        except StopIteration:
            pass


if __name__ == "__main__":
    main()
