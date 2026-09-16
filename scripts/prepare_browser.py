"""Create a disposable browser user and workspace; never change a person's example collection."""

import json
from pathlib import Path
from uuid import uuid4

from catalogforge.auth import hasher
from catalogforge.config import settings
from catalogforge.models import Membership, User, Workspace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

root = Path(__file__).resolve().parents[1]
user_id, workspace_id = str(uuid4()), str(uuid4())
email, password = f"{user_id}@browser.catalogforge.local", "Browser-test-only-2026!"
with Session(create_engine(settings().database_url), expire_on_commit=False) as db, db.begin():
    db.add(
        User(id=user_id, email=email, name="Browser Tester", password_hash=hasher.hash(password))
    )
    db.add(Workspace(id=workspace_id, name="Browser verification · synthetic"))
    db.flush()
    db.add(Membership(workspace_id=workspace_id, user_id=user_id, role="reviewer"))
(root / ".local").mkdir(exist_ok=True)
(root / ".local/browser-workspace.json").write_text(
    json.dumps(
        {"workspace_id": workspace_id, "user_id": user_id, "email": email, "password": password}
    )
)
print(f"Prepared isolated browser workspace {workspace_id}")
