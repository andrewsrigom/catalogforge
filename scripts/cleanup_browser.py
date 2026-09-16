"""Remove only the disposable identity recorded by prepare_browser.py."""

import json
import time
from pathlib import Path

from catalogforge.config import settings
from catalogforge.examples import workspace_id as example_workspace_id
from catalogforge.models import Base, User, Workspace
from catalogforge.walkthrough import workspace_id as walkthrough_workspace_id
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

root = Path(__file__).resolve().parents[1]
path = root / ".local/browser-workspace.json"
if not path.exists():
    raise SystemExit("No browser test workspace to clean up")
config = json.loads(path.read_text())
engine = create_engine(settings().database_url)
ids = [config["workspace_id"]]
user_id = config.get("user_id")
if user_id:
    ids.extend([example_workspace_id(user_id), walkthrough_workspace_id(user_id)])
for wid in ids:
    for _ in range(100):
        with engine.connect() as conn:
            active = conn.scalar(
                text(
                    "SELECT count(*) FROM procrastinate_jobs WHERE status='doing' AND args->>'workspace_id'=:id"
                ),
                {"id": wid},
            )
        if not active:
            break
        time.sleep(0.2)
    assert not active, "Wait for browser test jobs to finish"
with Session(engine) as db, db.begin():
    if user_id:
        user = db.get(User, user_id)
        assert (
            user
            and user.email == config["email"]
            and user.email.endswith("@browser.catalogforge.local")
        )
    for wid in ids:
        ws = db.get(Workspace, wid)
        if not ws:
            continue
        assert ws.name in {
            "Browser verification · synthetic",
            "Northstar · Guided examples",
            "Northstar · Guided walkthrough",
        }
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
        db.delete(ws)
    if user_id:
        db.execute(text("DELETE FROM auth_sessions WHERE user_id=:id"), {"id": user_id})
        db.delete(user)
path.unlink()
print("Removed only recorded browser test workspaces and temporary user")
