"""Exercise the real API, PostgreSQL and independent worker; no mocks."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
from catalogforge.cli import DEMO_WORKSPACE
from catalogforge.config import settings

ROOT = Path(__file__).resolve().parents[1]
client = httpx.Client(base_url=os.getenv("TEST_API_URL", "http://127.0.0.1:8188/api"), timeout=30)
response = client.post(
    "/auth/login",
    json={"email": "reviewer@catalogforge.local", "password": settings().demo_password},
)
response.raise_for_status()
session = response.json()
demo = next((w for w in session["workspaces"] if w["id"] == DEMO_WORKSPACE), None)
assert demo is not None, "Seed the synthetic demo before running this smoke test"
client.headers.update({"x-workspace-id": demo["id"], "x-csrf-token": session["csrf"]})


settings_response = client.get("/settings")
settings_response.raise_for_status()
if settings_response.json()["mode"] != "fixture":
    raise SystemExit("This smoke test requires an isolated fixture environment")


def request(method, url, **kwargs):
    result = client.request(method, url, **kwargs)
    if result.is_error:
        raise AssertionError(f"{method} {url}: {result.status_code} {result.text}")
    return result


products = request("GET", "/products").json()
sources = request("GET", "/sources").json()
assert len(products) == 50
assert all(s["status"] == "ready" for s in sources), sources
chosen = [
    p
    for p in products
    if p["sku"] in {"CF-0001", "CF-0003", "CF-0006", "CF-0007", "CF-0010", "CF-0036"}
]
batch = request(
    "POST",
    "/batches",
    json={"product_ids": [p["id"] for p in chosen], "title": "Verified demo journey"},
).json()
details = []
for run in batch["runs"]:
    for _ in range(150):
        detail = request("GET", f"/runs/{run['id']}").json()
        if detail["run"]["status"] in {"waiting_review", "failed"}:
            break
        time.sleep(0.2)
    assert detail["run"]["status"] == "waiting_review", detail
    details.append(detail)
conflict = next(d for d in details if d["product"]["sku"] == "CF-0003")
assert len([c for c in conflict["candidates"] if c["status"] == "conflicting"]) == 2
unknown = next(d for d in details if d["product"]["sku"] == "CF-0036")
assert all(c["status"] == "insufficient_evidence" for c in unknown["candidates"])
if "--compose" in sys.argv:
    container = subprocess.check_output(
        ["docker", "compose", "ps", "-q", "worker"], cwd=ROOT, text=True
    ).strip()
    old_pid = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.State.Pid}}", container], text=True
    ).strip()
    subprocess.run(["docker", "compose", "restart", "worker"], cwd=ROOT, check=True)
    new_pid = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.State.Pid}}", container], text=True
    ).strip()
else:
    old_pid = (ROOT / ".local/worker.pid").read_text()
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "scripts/dev.py", "restart", "worker"],
        cwd=ROOT,
        check=True,
    )
    new_pid = (ROOT / ".local/worker.pid").read_text()
assert new_pid != old_pid
for detail in details:
    fresh = request("GET", f"/runs/{detail['run']['id']}").json()
    assert fresh["run"]["interrupt_id"] == detail["run"]["interrupt_id"]
    assert len(fresh["candidates"]) == len(detail["candidates"])
    decisions = []
    for candidate in detail["candidates"]:
        action = "approve" if candidate["status"] == "supported" else "reject"
        reason = ""
        if candidate["status"] == "conflicting" and candidate["normalized_value"] == "Nylon":
            action = "approve"
            reason = "Selected the primary synthetic technical record after comparing both sources"
        # Approving a conflict atomically rejects alternatives; do not submit a second conflicting decision.
        if candidate["status"] == "conflicting" and action == "reject":
            continue
        decisions.append(
            {
                "candidate_id": candidate["id"],
                "version": candidate["version"],
                "action": action,
                "reason": reason,
            }
        )
    body = {
        "interrupt_id": detail["run"]["interrupt_id"],
        "product_revision": detail["product"]["revision"],
        "idempotency_key": str(uuid4()),
        "decisions": decisions,
    }
    review = request("POST", f"/runs/{detail['run']['id']}/review", json=body).json()
    duplicate = request("POST", f"/runs/{detail['run']['id']}/review", json=body).json()
    assert duplicate["id"] == review["id"]
for detail in details:
    for _ in range(150):
        fresh = request("GET", f"/runs/{detail['run']['id']}").json()
        if fresh["run"]["status"] in {"completed", "failed"}:
            break
        time.sleep(0.2)
    assert fresh["run"]["status"] == "completed", fresh
export = request("POST", "/exports", json={"idempotency_key": str(uuid4())}).json()
archive = request("GET", f"/exports/{export['id']}/file").content
(ROOT / ".local/verified-export.zip").write_bytes(archive)
report = {
    "status": "passed",
    "products": len(products),
    "sources": len(sources),
    "product_runs": len(details),
    "worker_restart_verified": True,
    "duplicate_review_verified": True,
    "export_bytes": len(archive),
    "batch_id": batch["id"],
    "mode": "fixture",
}
(ROOT / ".local/smoke-result.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
