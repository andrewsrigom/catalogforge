import asyncio
import logging
from contextlib import suppress
from typing import Any

import procrastinate
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from procrastinate.jobs import Status
from psycopg.conninfo import make_conninfo
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .db import transaction
from .enrichment import enrichment_graph
from .ingestion import ingestion_graph
from .models import (
    Outbox,
    ProductRun,
    Review,
    SourceDocument,
    WorkerHeartbeat,
    WorkflowEvent,
    now,
    uid,
)
from .provider_meter import CallScope, scope
from .services import get_scoped

WORKER_ID = uid()

logger = logging.getLogger("catalogforge.worker")
queue = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=settings().pg_url))


def checkpoint_connection() -> str:
    return make_conninfo(settings().pg_url, options="-c search_path=checkpoints")


@queue.task(name="catalogforge.execute", retry=procrastinate.RetryStrategy(max_attempts=2, wait=2))
async def execute(workspace_id: str, kind: str, entity_id: str, payload: dict):
    is_document = kind == "ingest"
    model = SourceDocument if is_document else ProductRun
    async with transaction() as db:
        entity = await get_scoped(db, model, entity_id, workspace_id, lock=True)
        if is_document and entity.status == "ready":
            return
        if not is_document and (entity.cancelled or entity.status == "completed"):
            return
        if kind == "resume":
            review = await get_scoped(db, Review, payload["review_id"], workspace_id)
            if review.status == "applied" and entity.status in {"waiting_review", "completed"}:
                return
        if not is_document:
            entity.attempt += 1
            db.add(
                WorkflowEvent(
                    workspace_id=workspace_id,
                    run_id=entity.id,
                    step="Resuming saved workflow"
                    if kind == "resume"
                    else "Retrying saved workflow"
                    if entity.attempt > 1
                    else "Execution started",
                    details={"attempt": entity.attempt, "kind": kind},
                )
            )
        entity.status = "processing" if kind != "resume" else "resuming"
        entity.error = None
    token = scope.set(
        CallScope(
            workspace_id,
            "document" if is_document else "batch",
            entity_id if is_document else entity.batch_id,
            entity_id,
        )
    )
    try:
        async with AsyncPostgresSaver.from_conn_string(checkpoint_connection()) as saver:
            graph = ingestion_graph(saver) if is_document else enrichment_graph(saver)
            config = {
                "configurable": {
                    "thread_id": f"{workspace_id}:{'document' if is_document else 'product'}:{entity_id}"
                },
                "recursion_limit": 40,
            }
            snapshot = await graph.aget_state(config)
            interruptions = [item for task in snapshot.tasks for item in task.interrupts]
            value: Any = (
                None
                if snapshot.values
                else {
                    "workspace_id": workspace_id,
                    "document_id" if is_document else "run_id": entity_id,
                }
            )
            if kind == "resume":
                async with transaction() as db:
                    review = await get_scoped(db, Review, payload["review_id"], workspace_id)
                    if interruptions:
                        if review.interrupt_id not in {item.id for item in interruptions}:
                            raise ValueError("The saved interrupt no longer matches this review")
                        value = Command(resume={review.interrupt_id: {"review_id": review.id}})
                    elif review.status != "applied" and not snapshot.next:
                        raise ValueError("No paused workflow is available to resume")
            if not interruptions or kind == "resume":
                async with asyncio.timeout(settings().max_run_seconds):
                    await graph.ainvoke(value, config)
            snapshot = await graph.aget_state(config)
            interruptions = [item for task in snapshot.tasks for item in task.interrupts]
            if not is_document and interruptions:
                async with transaction() as db:
                    run = await get_scoped(db, ProductRun, entity_id, workspace_id, lock=True)
                    if not run.cancelled:
                        run.status = "waiting_review"
                        run.step = "Waiting for review"
                        run.interrupt_id = interruptions[0].id
                        db.add(
                            WorkflowEvent(
                                workspace_id=workspace_id, run_id=run.id, step="Waiting for review"
                            )
                        )
    except Exception as exc:
        message = str(exc)[:700] or type(exc).__name__
        async with transaction() as db:
            entity = await get_scoped(db, model, entity_id, workspace_id)
            entity.status = "cancelled" if not is_document and entity.cancelled else "failed"
            entity.error = message
            db.add(
                WorkflowEvent(
                    workspace_id=workspace_id,
                    step="Processing failed",
                    document_id=entity_id if is_document else None,
                    run_id=None if is_document else entity_id,
                    details={"error": message},
                )
            )
            if kind == "resume":
                review = await get_scoped(db, Review, payload["review_id"], workspace_id)
                if review.status != "applied":
                    review.status = "failed"
                    review.error = message
        raise
    finally:
        scope.reset(token)


async def dispatch_once():
    # Commit requested jobs in the same business transaction; delivery can safely repeat.
    async with transaction() as db:
        messages = (
            await db.scalars(
                select(Outbox)
                .where(Outbox.delivered.is_(False))
                .order_by(Outbox.created_at)
                .limit(30)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for message in messages:
            await execute.configure(
                lock=f"{message.workspace_id}:{message.entity_id}",
                priority={"resume": 100, "ingest": 10}.get(message.kind, 0),
            ).defer_async(
                workspace_id=message.workspace_id,
                kind=message.kind,
                entity_id=message.entity_id,
                payload=message.payload,
            )
            message.delivered = True


async def exhaust_stalled_job(job) -> bool:
    args: dict[str, Any] = job.task_kwargs
    async with transaction() as db:
        from .services import get_workspace_lock

        await get_workspace_lock(db, args["workspace_id"])
        model = SourceDocument if args["kind"] == "ingest" else ProductRun
        entity = await get_scoped(db, model, args["entity_id"], args["workspace_id"], lock=True)
        final = entity.status in {"ready", "completed", "waiting_review", "cancelled"}
        if not final:
            message = "Worker stopped unexpectedly three times. Automatic retries are exhausted; inspect the source or run and retry manually."
            entity.status, entity.error = "failed", message
            if model is ProductRun:
                entity.step = "Recovery needs attention"
            db.add(
                WorkflowEvent(
                    workspace_id=args["workspace_id"],
                    document_id=entity.id if model is SourceDocument else None,
                    run_id=entity.id if model is ProductRun else None,
                    step="Recovery needs attention",
                    details={"error": message, "job_id": job.id},
                )
            )
            if args["kind"] == "resume":
                review = await get_scoped(
                    db, Review, args["payload"]["review_id"], args["workspace_id"]
                )
                if review.status != "applied":
                    review.status, review.error = "failed", message
        return final


async def recover_stalled():
    # One sweeper across workers. Heartbeats, not job duration, establish liveness.
    async with transaction() as db:
        acquired = await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext('catalogforge.recovery'))")
        )
        if not acquired:
            return
        for job in await queue.job_manager.get_stalled_jobs(
            task_name="catalogforge.execute", seconds_since_heartbeat=40
        ):
            if job.attempts < 3:
                await queue.job_manager.retry_job(job)
            else:
                # Business outcome commits first. If interrupted here, the next sweep safely repeats.
                final = await exhaust_stalled_job(job)
                await queue.job_manager.finish_job(
                    job, Status.SUCCEEDED if final else Status.FAILED, delete_job=False
                )


async def dispatch_loop():
    rounds = 0
    while True:
        try:
            await dispatch_once()
            async with transaction() as db:
                await db.execute(
                    insert(WorkerHeartbeat)
                    .values(id=WORKER_ID, last_seen=now())
                    .on_conflict_do_update(index_elements=["id"], set_={"last_seen": now()})
                )
            if rounds % 15 == 0:
                await recover_stalled()
            rounds += 1
        except Exception:
            logger.exception("Outbox dispatch or stalled-job recovery failed; retrying")
        await asyncio.sleep(2)


async def main():
    logging.basicConfig(level=logging.INFO)
    async with queue.open_async():
        dispatcher = asyncio.create_task(dispatch_loop())
        try:
            await queue.run_worker_async(concurrency=settings().worker_concurrency)
        finally:
            dispatcher.cancel()
            with suppress(asyncio.CancelledError):
                await dispatcher


if __name__ == "__main__":
    asyncio.run(main())
