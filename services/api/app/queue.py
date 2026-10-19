from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Job

QUEUE_NAME = "clipfactory:wakeup"


def job_key(
    kind: str,
    project_id: str,
    clip_id: str | None = None,
    key_suffix: str | None = None,
) -> str:
    return f"{kind}:{project_id}:{key_suffix or clip_id or 'source'}"


async def find_job(
    session: AsyncSession,
    *,
    kind: str,
    project_id: str,
    clip_id: str | None = None,
    key_suffix: str | None = None,
) -> Job | None:
    return await session.scalar(
        select(Job).where(
            Job.idempotency_key == job_key(kind, project_id, clip_id, key_suffix)
        )
    )


async def create_job(
    session: AsyncSession,
    *,
    kind: str,
    project_id: str,
    clip_id: str | None = None,
    key_suffix: str | None = None,
) -> Job:
    key = job_key(kind, project_id, clip_id, key_suffix)
    existing = await find_job(
        session,
        kind=kind,
        project_id=project_id,
        clip_id=clip_id,
        key_suffix=key_suffix,
    )
    if existing:
        return existing
    job = Job(
        kind=kind,
        project_id=project_id,
        clip_id=clip_id,
        idempotency_key=key,
        run_after=datetime.now(UTC),
    )
    try:
        async with session.begin_nested():
            session.add(job)
            await session.flush()
    except IntegrityError:
        existing = await find_job(
            session,
            kind=kind,
            project_id=project_id,
            clip_id=clip_id,
            key_suffix=key_suffix,
        )
        if existing:
            return existing
        raise
    return job


async def retry_failed_job(session: AsyncSession, project_id: str) -> Job | None:
    job = await session.scalar(
        select(Job)
        .where(Job.project_id == project_id, Job.status == "failed")
        .order_by(Job.updated_at.desc())
        .limit(1)
    )
    if not job:
        return None
    job.status = "pending"
    job.attempt = 0
    job.run_after = datetime.now(UTC)
    job.last_error = None
    job.lock_token = None
    job.lease_expires_at = None
    return job


async def notify_worker(job_id: str) -> None:
    """Best-effort wakeup. PostgreSQL remains the durable job source."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.lpush(QUEUE_NAME, job_id)
    except OSError:
        pass
    finally:
        await client.aclose()
