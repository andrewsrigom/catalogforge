"""Evaluate the 12 guided examples using their real API, worker and labeled outcomes."""

import argparse
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from catalogforge.config import settings
from catalogforge.models import Base, Workspace
from sqlalchemy import delete, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/tests"))
from conftest import SYNC_ENGINE, workspace  # noqa: E402


@contextmanager
def example_client():
    if settings().ai_mode != "fixture":
        raise SystemExit(
            "This verification requires AI_MODE=fixture; real-provider calls are not part of this test"
        )
    context = workspace.__wrapped__()
    ws = next(context)
    client = ws["client"]
    wid = None
    try:
        installed = client.post("/examples/install")
        installed.raise_for_status()
        wid = installed.json()["workspace_id"]
        client.headers["x-workspace-id"] = wid
        yield client
    finally:
        if wid:
            # Only the newly generated test user's synthetic workspace is removed.
            with SYNC_ENGINE.begin() as db:
                name = db.scalar(text("SELECT name FROM workspaces WHERE id=:id"), {"id": wid})
                assert name == "Northstar · Guided examples"
                db.execute(
                    text("DELETE FROM procrastinate_jobs WHERE args->>'workspace_id'=:id"),
                    {"id": wid},
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
        try:
            next(context)
        except StopIteration:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evals/results-workday-v1.json")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "fixtures/workday/manifest.json").read_text())
    with example_client() as client:
        for _ in range(150):
            state = client.get("/examples").json()
            if state["sources_ready"] == state["sources_total"]:
                break
            time.sleep(0.2)
        assert state["sources_ready"] == 5, state
        started = time.perf_counter()
        cases = []
        failures = []
        evidence = 0
        for case in manifest["cases"]:
            response = client.post("/examples/" + case["sku"] + "/run")
            response.raise_for_status()
            run = response.json()
            for _ in range(200):
                detail = client.get("/runs/" + run["id"]).json()
                if detail["run"]["status"] in {"waiting_review", "completed", "failed"}:
                    break
                time.sleep(0.15)
            if detail["run"]["status"] != "waiting_review":
                failures.append(
                    f"{case['sku']}: expected a fresh review; got {detail['run']['status']}"
                )
            checks = []
            for attr, expected in case["expected"].items():
                candidates = [c for c in detail["candidates"] if c["attribute_key"] == attr]
                statuses = {c["status"] for c in candidates}
                values = [
                    c["normalized_value"] for c in candidates if c["normalized_value"] is not None
                ]
                ok = statuses == {expected["status"]} and sorted(values, key=str) == sorted(
                    expected["values"], key=str
                )
                if not ok:
                    failures.append(
                        f"{case['sku']}/{attr}: {statuses}, {values}; expected {expected}"
                    )
                for candidate in candidates:
                    for link in candidate["evidence"]:
                        evidence += 1
                        source = client.get("/sources/" + link["document_id"]).json()
                        chunk = next(c for c in source["chunks"] if c["id"] == link["chunk_id"])
                        assert (
                            link["quote"] in chunk["text"]
                            and source["document"]["filename"] in case["evidence_files"]
                        ), (case["sku"], link)
                        if case["sku"] == "NS-006":
                            assert link["identity_basis"]["kind"] == "family"
                checks.append({"attribute": attr, "passed": ok})
            cases.append(
                {
                    "sku": case["sku"],
                    "run_id": run["id"],
                    "status": detail["run"]["status"],
                    "checks": checks,
                }
            )
        result = {
            "evaluation_kind": "deterministic_fixture_integration",
            "dataset": "northstar-workday-v1",
            "products": len(cases),
            "attribute_checks": sum(len(c["checks"]) for c in cases),
            "passed_checks": sum(x["passed"] for c in cases for x in c["checks"]),
            "evidence_links_verified": evidence,
            "wall_seconds": round(time.perf_counter() - started, 3),
            "live_model_evaluation": False,
            "paid_model_calls": 0,
            "token_usage": None,
            "cost": None,
            "failures": failures,
            "cases": cases,
        }
        (ROOT / args.output).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2))
        assert not failures, failures


if __name__ == "__main__":
    main()
