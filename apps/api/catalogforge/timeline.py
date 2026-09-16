"""Read-only execution history, scoped before accessing graph checkpoints."""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from . import services
from .enrichment import enrichment_graph
from .models import Candidate, ProductRun, Review, WorkflowEvent
from .worker import checkpoint_connection


async def execution_timeline(db, actor, run_id):
    run = await services.get_scoped(db, ProductRun, run_id, actor.workspace_id)
    events = (
        await db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.workspace_id == actor.workspace_id, WorkflowEvent.run_id == run.id)
            .order_by(WorkflowEvent.sequence.desc())
            .limit(201)
        )
    ).all()
    reviews = (
        await db.scalars(
            select(Review)
            .where(Review.workspace_id == actor.workspace_id, Review.run_id == run.id)
            .order_by(Review.created_at)
        )
    ).all()
    keys = dict(
        (
            await db.execute(
                select(Candidate.id, Candidate.attribute_key).where(
                    Candidate.workspace_id == actor.workspace_id, Candidate.run_id == run.id
                )
            )
        ).all()
    )
    checkpoints = []
    async with AsyncPostgresSaver.from_conn_string(checkpoint_connection()) as saver:
        graph = enrichment_graph(saver)
        async for snapshot in graph.aget_state_history(
            {"configurable": {"thread_id": f"{actor.workspace_id}:product:{run.id}"}}, limit=101
        ):
            checkpoints.append(
                {
                    "id": snapshot.config["configurable"]["checkpoint_id"],
                    "created_at": snapshot.created_at,
                    "step": (snapshot.metadata or {}).get("step", 0),
                    "next_nodes": list(snapshot.next),
                    "interrupted": any(task.interrupts for task in snapshot.tasks),
                }
            )
    return {
        "run_id": run.id,
        "status": run.status,
        "attempt": run.attempt,
        "events": list(reversed(events[:200])),
        "checkpoints": list(reversed(checkpoints[:100])),
        "truncated": len(events) > 200 or len(checkpoints) > 100,
        "reviews": [
            {
                "id": review.id,
                "status": review.status,
                "created_at": review.created_at,
                "decisions": [
                    {
                        "attribute_key": keys.get(decision["candidate_id"], ""),
                        "candidate_id": decision["candidate_id"],
                        "action": decision["action"],
                        "reason": decision.get("reason", ""),
                    }
                    for decision in review.decisions
                ],
            }
            for review in reviews
        ],
    }
