"""Background worker: ``python -m newsroom.worker``. Safe to run as multiple replicas."""

import asyncio
import contextlib
import signal

import structlog

import newsroom.models  # noqa: F401  (registers every mapper)
from newsroom.core.config import get_settings
from newsroom.core.db import create_engine, create_sessionmaker
from newsroom.core.logging import configure_logging
from newsroom.worker.jobs import JOBS

log = structlog.get_logger("newsroom.worker")


async def run() -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker_started", poll_seconds=settings.worker_poll_seconds, jobs=list(JOBS))
    try:
        while not stop.is_set():
            for name, job in JOBS.items():
                try:
                    async with sessionmaker() as db:
                        affected = await job(db)
                    if affected:
                        log.info("job_done", job=name, affected=affected)
                except Exception:
                    log.exception("job_failed", job=name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
    finally:
        await engine.dispose()
        log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(run())
