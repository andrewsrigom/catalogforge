"""Verify seed, reindex and reset against local Compose; resets the synthetic demo."""

import json
import os
import subprocess
import time
from pathlib import Path

from catalogforge.config import settings
from sqlalchemy import create_engine, text

root = Path(__file__).resolve().parents[1]
os.chdir(root)
engine = create_engine(settings().database_url)


def compose(*args):
    subprocess.run(["docker", "compose", *args], check=True, cwd=root)


def snapshot():
    with engine.connect() as db:
        return {
            name: [tuple(row) for row in db.execute(text(sql))]
            for name, sql in {
                "products": "SELECT id,workspace_id FROM products ORDER BY id",
                "documents": "SELECT id,workspace_id FROM source_documents ORDER BY id",
                "chunks": "SELECT id,workspace_id FROM chunks ORDER BY id",
            }.items()
        }


before = snapshot()
compose(
    "run",
    "--rm",
    "--no-deps",
    "init",
    "uv",
    "run",
    "--no-sync",
    "python",
    "-m",
    "catalogforge.cli",
    "seed",
)
assert snapshot() == before, "Seed changed entity identities or counts"
compose("stop", "api", "worker")
try:
    compose(
        "run",
        "--rm",
        "--no-deps",
        "init",
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "catalogforge.cli",
        "reindex",
    )
finally:
    compose("up", "-d", "api", "worker")
for _ in range(120):
    with engine.connect() as db:
        status = list(
            db.execute(text("SELECT status FROM source_documents WHERE active=true")).scalars()
        )
    if status and all(s == "ready" for s in status):
        break
    time.sleep(0.5)
assert all(s == "ready" for s in status), status
assert snapshot() == before, "Reindex changed chunk, document or product identities"
compose("stop", "api", "worker")
try:
    compose(
        "run",
        "--rm",
        "--no-deps",
        "init",
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "catalogforge.cli",
        "demo-reset",
    )
finally:
    compose("up", "-d", "api", "worker")
subprocess.run([str(root / ".venv/bin/python"), "scripts/wait_ready.py"], check=True)
after = snapshot()
demo = "00000000-0000-0000-0000-000000000001"
for key in before:
    assert [r for r in before[key] if r[1] != demo] == [r for r in after[key] if r[1] != demo], key
assert len([p for p in after["products"] if p[1] == demo]) == 50
assert len([p for p in after["documents"] if p[1] == demo]) == 5
result = {
    "status": "passed",
    "seed_idempotence": True,
    "reindex_preserves_chunk_ids": True,
    "reset_preserves_other_workspaces": True,
    "demo_products": 50,
    "demo_sources": 5,
}
(root / ".local/maintenance-result.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
