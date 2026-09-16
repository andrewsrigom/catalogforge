"""Maintenance commands restricted to the synthetic demonstration workspace."""

import asyncio

from sqlalchemy import create_engine, delete, text, update

from .config import settings
from .models import Base, Workspace

DEMO_WORKSPACE = "00000000-0000-0000-0000-000000000001"


def reset_demo():
    engine = create_engine(settings().database_url)
    with engine.begin() as connection:
        name = connection.execute(
            text("SELECT name FROM workspaces WHERE id=:wid FOR UPDATE"), {"wid": DEMO_WORKSPACE}
        ).scalar_one_or_none()
        if name is not None and name != "ForgeWorks · Synthetic demo":
            raise ValueError(
                "Refusing reset: the fixed demo workspace no longer has its synthetic name."
            )
        running = connection.execute(
            text(
                "SELECT count(*) FROM procrastinate_jobs WHERE args->>'workspace_id'=:wid AND status='doing'"
            ),
            {"wid": DEMO_WORKSPACE},
        ).scalar_one()
        if running:
            raise ValueError(
                "Stop the API and worker and allow running jobs to finish before demo-reset."
            )
        connection.execute(
            text("DELETE FROM procrastinate_jobs WHERE args->>'workspace_id'=:wid"),
            {"wid": DEMO_WORKSPACE},
        )
        for table in reversed(Base.metadata.sorted_tables):
            if "workspace_id" in table.c and table.name != "memberships":
                connection.execute(delete(table).where(table.c.workspace_id == DEMO_WORKSPACE))
        for checkpoint_table in ["checkpoint_writes", "checkpoint_blobs", "checkpoints"]:
            connection.execute(
                text(f"DELETE FROM checkpoints.{checkpoint_table} WHERE thread_id LIKE :prefix"),
                {"prefix": DEMO_WORKSPACE + ":%"},
            )
        connection.execute(
            update(Workspace).where(Workspace.id == DEMO_WORKSPACE).values(source_revision=0)
        )
    engine.dispose()
    from .cli import seed

    asyncio.run(seed())
    print(
        "Synthetic demo reset. Other workspaces and users are unchanged. Old stored files are retained."
    )


def verify_export(path):
    import csv
    import io
    import json
    import zipfile

    with zipfile.ZipFile(path) as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("catalog.csv").decode("utf-8-sig"))))
        evidence = json.loads(archive.read("evidence.json"))
    assert all(e["source_supports_final_value"] != e["manual_edit"] for e in evidence)
    return {"products": len(rows), "evidence_records": len(evidence)}
