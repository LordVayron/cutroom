import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import and_, or_, select, update

from app.config import settings
from app.db import SessionLocal
from app.models import Job, Project
from app.pipeline import (
    PermanentPipelineError,
    process_ingest,
    process_inspect,
    process_render,
    process_render_all,
    process_score,
)
from app.queue import QUEUE_NAME


async def claim_job() -> tuple[str, str] | None:
    async with SessionLocal() as session:
        now = datetime.now(UTC)
        job = await session.scalar(
            select(Job)
            .where(
                or_(
                    and_(Job.status == "pending", Job.run_after <= now),
                    and_(
                        Job.status == "running",
                        or_(Job.lease_expires_at.is_(None), Job.lease_expires_at <= now),
                    ),
                )
            )
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        token = str(uuid4())
        job.status = "running"
        job.attempt += 1
        job.lock_token = token
        job.lease_expires_at = now + timedelta(
            seconds=settings.worker_job_lease_seconds
        )
        await session.commit()
        return job.id, token


async def heartbeat(job_id: str, lock_token: str) -> None:
    while True:
        await asyncio.sleep(settings.worker_heartbeat_seconds)
        async with SessionLocal() as session:
            result = await session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "running",
                    Job.lock_token == lock_token,
                )
                .values(
                    lease_expires_at=datetime.now(UTC)
                    + timedelta(seconds=settings.worker_job_lease_seconds)
                )
            )
            await session.commit()
            if result.rowcount == 0:
                return


async def run_job(job_id: str, lock_token: str) -> None:
    heartbeat_task = asyncio.create_task(heartbeat(job_id, lock_token))
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if not job or job.status != "running" or job.lock_token != lock_token:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            return
        project = await session.get(Project, job.project_id)
        if project and project.status == "failed":
            project.status = "queued" if job.kind in {"ingest", "score"} else "ready"
            project.error = None
            await session.commit()
        elif project and job.attempt > 1:
            active_states = {
                "ingest": {"ingesting", "transcribing", "scoring"},
                "score": {"scoring"},
                "render": {"rendering"},
                "render_all": {"rendering"},
            }.get(job.kind, set())
            if project.status in active_states:
                project.status = "queued" if job.kind in {"ingest", "score"} else "ready"
                project.error = None
                await session.commit()
        try:
            if job.kind == "ingest":
                await process_ingest(session, job.project_id)
            elif job.kind == "score":
                await process_score(session, job.project_id)
            elif job.kind == "render" and job.clip_id:
                await process_render(session, job.project_id, job.clip_id)
            elif job.kind == "render_all":
                await process_render_all(session, job.project_id)
            elif job.kind == "inspect" and job.clip_id:
                await process_inspect(session, job.project_id, job.clip_id)
            else:
                raise ValueError(f"Unsupported job kind: {job.kind}")
            job = await session.get(Job, job_id)
            if job and job.lock_token == lock_token:
                job.status = "done"
                job.last_error = None
                job.lock_token = None
                job.lease_expires_at = None
                await session.commit()
        except Exception as exc:
            await session.rollback()
            job = await session.get(Job, job_id)
            project = await session.get(Project, job.project_id) if job else None
            if not job or job.lock_token != lock_token:
                return
            job.last_error = str(exc)[:4000]
            retryable = not isinstance(exc, PermanentPipelineError)
            if retryable and job.attempt < settings.worker_max_retries:
                job.status = "pending"
                job.run_after = datetime.now(UTC) + timedelta(seconds=2**job.attempt)
            else:
                job.status = "failed"
            job.lock_token = None
            job.lease_expires_at = None
            if project and job.kind != "inspect":
                project.status = "failed"
                project.error = job.last_error
                project.retryable = retryable
            await session.commit()
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            claimed = await claim_job()
            if claimed:
                await run_job(*claimed)
                continue
            try:
                await redis.brpop(QUEUE_NAME, timeout=2)
            except OSError:
                await asyncio.sleep(2)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
