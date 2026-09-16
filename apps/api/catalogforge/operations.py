from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from .models import (
    Outbox,
    ProductRun,
    ProviderBudget,
    ProviderCall,
    SourceDocument,
    WorkerHeartbeat,
    now,
)


async def summary(db, workspace_id: str):
    current = now()
    heartbeat = await db.scalar(select(func.max(WorkerHeartbeat.last_seen)))
    counts = {}
    oldest = []
    failures: list[dict[str, Any]] = []
    models: list[tuple[str, Any]] = [("runs", ProductRun), ("documents", SourceDocument)]
    for label, model in models:
        counts[label] = dict(
            (
                await db.execute(
                    select(model.status, func.count())
                    .where(model.workspace_id == workspace_id)
                    .group_by(model.status)
                )
            ).all()
        )
        queued = await db.scalar(
            select(func.min(model.created_at)).where(
                model.workspace_id == workspace_id, model.status == "queued"
            )
        )
        if queued:
            oldest.append(queued)
        failed = (
            await db.scalars(
                select(model)
                .where(model.workspace_id == workspace_id, model.status == "failed")
                .order_by(model.created_at.desc())
                .limit(5)
            )
        ).all()
        failures.extend(
            {
                "kind": label,
                "id": item.id,
                "error": item.error,
                "created_at": item.created_at.isoformat(),
            }
            for item in failed
        )
    pending_dispatch = await db.scalar(
        select(func.count())
        .select_from(Outbox)
        .where(Outbox.workspace_id == workspace_id, Outbox.delivered.is_(False))
    )
    budgets = (
        await db.scalars(
            select(ProviderBudget)
            .where(ProviderBudget.workspace_id == workspace_id)
            .order_by(
                (ProviderBudget.scope_key == "workspace").desc(), ProviderBudget.created_at.desc()
            )
            .limit(100)
        )
    ).all()
    usage = (
        await db.execute(
            select(
                ProviderCall.operation,
                ProviderCall.status,
                func.count(),
                func.sum(ProviderCall.charged_tokens),
                func.sum(ProviderCall.charged_cost_micros),
            )
            .where(ProviderCall.workspace_id == workspace_id)
            .group_by(ProviderCall.operation, ProviderCall.status)
        )
    ).all()
    unknown = await db.scalar(
        select(func.count())
        .select_from(ProviderCall)
        .where(ProviderCall.workspace_id == workspace_id, ProviderCall.usage.is_(None))
    )
    return {
        "worker": {
            "healthy": bool(heartbeat and heartbeat > current - timedelta(seconds=40)),
            "last_seen": heartbeat.isoformat() if heartbeat else None,
        },
        "queue": {
            "counts": counts,
            "pending_dispatch": pending_dispatch,
            "oldest_wait_seconds": max(0, round((current - min(oldest)).total_seconds()))
            if oldest
            else 0,
        },
        "failures": sorted(failures, key=lambda row: row["created_at"], reverse=True)[:5],
        "next_step": "Inspect failed items and retry only after fixing their cause."
        if failures
        else "Worker unavailable: check the worker process."
        if not heartbeat or heartbeat < current - timedelta(seconds=40)
        else "Review paused runs or wait for queued work.",
        "provider_usage": [
            {
                "operation": op,
                "status": status,
                "calls": count,
                "charged_tokens": tokens,
                "charged_cost_micros": cost,
            }
            for op, status, count, tokens, cost in usage
        ],
        "unknown_usage_calls": unknown,
        "budgets": [
            {
                "scope": b.scope_key,
                "limits": b.limits,
                "calls": b.calls,
                "charged_tokens": b.charged_tokens,
                "charged_cost_micros": b.charged_cost_micros,
            }
            for b in budgets
        ],
    }
