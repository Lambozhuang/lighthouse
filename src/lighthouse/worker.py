"""The background worker: turns pending inbox items into notes.

    python -m lighthouse.worker

The `inbox_items` table is the job queue, so there is no broker to run. The worker takes one
pending item at a time, marks it `processing`, runs the ingest pipeline, and the item ends up
`done` (with a note) or `failed` (with a reason the user can read).
"""

import asyncio
import contextlib
import logging
import signal

from lighthouse import db
from lighthouse.config import get_settings
from lighthouse.ingest import pipeline
from lighthouse.ingest.errors import IngestError
from lighthouse.ingest.pipeline import Item

log = logging.getLogger("lighthouse.worker")

# After a failed attempt an item waits this long, times the attempts so far, before the next
# one. Retrying at once rarely helps against a rate limit or an outage.
RETRY_DELAY_SECONDS = 30
# A hung model call or a stalled page must not block the queue forever.
ITEM_TIMEOUT_SECONDS = 180


async def claim(conn: db.Conn) -> Item | None:
    """Take the oldest pending item and mark it `processing`. None when nothing is ready.

    FOR UPDATE locks the selected row until the transaction ends; SKIP LOCKED makes a second
    worker running the same query step over that row instead of waiting for it. So two
    workers can never claim the same item, and neither blocks the other.
    """
    row = await db.fetch_one(
        conn,
        """
        update inbox_items
        set status = 'processing', attempts = attempts + 1, updated_at = now()
        where id = (
            select id from inbox_items
            where status = 'pending'
              and updated_at <= now() - make_interval(secs => %s * attempts)  -- retry delay; 0 for new items
            order by created_at
            limit 1
            for update skip locked
        )
        returning id, user_id, kind, content, attempts
        """,
        [RETRY_DELAY_SECONDS],
    )
    return Item(**row) if row else None


async def run_once() -> bool:
    """Claim and process one item. False when there was nothing to do."""
    # The claim commits on its own, before the slow work starts. The row lock is held for
    # milliseconds, and everyone (the user's inbox view, other workers) sees `processing`.
    async with db.service_conn() as conn:
        item = await claim(conn)
    if item is None:
        return False
    log.info("processing %s item %s (attempt %d)", item.kind, item.id, item.attempts)
    try:
        async with asyncio.timeout(ITEM_TIMEOUT_SECONDS):
            await pipeline.process(item)
    except IngestError as exc:
        # A failure the pipeline can explain; it says itself whether a retry could help.
        log.warning("item %s: %s", item.id, exc)
        await _record_failure(item, str(exc), retry=exc.retryable)
    except Exception as exc:
        # Anything else is a bug or an outage (model API down, database hiccup). The details go
        # to the log; the user gets a short message. Assume it may pass, so retry.
        log.exception("item %s failed", item.id)
        await _record_failure(item, f"Unexpected error ({type(exc).__name__}); retry later", retry=True)
    else:
        log.info("item %s done", item.id)
    return True


async def _record_failure(item: Item, message: str, *, retry: bool) -> None:
    retry = retry and item.attempts < get_settings().worker_max_attempts
    async with db.service_conn() as conn:
        # Back to `pending` for another attempt, or `failed` with the reason. `error` is only
        # set on failed items, as docs/API.md promises.
        await conn.execute(
            "update inbox_items set status = %s, error = %s, updated_at = now() "
            "where id = %s and status = 'processing'",
            ["pending" if retry else "failed", None if retry else message[:500], item.id],
        )


async def recover_stuck() -> None:
    """Deal with items a previous worker left in `processing` when it crashed or was killed.

    They go back to `pending`, unless they have used up their attempts: an item that takes the
    worker down every time must not be retried forever.

    This assumes one worker process. With several, a starting worker would also reset items
    that another one is working on right now; pipeline.process tolerates that (it re-checks the
    status before writing), but the work is done twice. A real multi-worker setup would give
    each claim a lease that expires instead.
    """
    max_attempts = get_settings().worker_max_attempts
    async with db.service_conn() as conn:
        failed = await conn.execute(
            "update inbox_items set status = 'failed', error = %s, updated_at = now() "
            "where status = 'processing' and attempts >= %s",
            ["Processing was interrupted too many times", max_attempts],
        )
        requeued = await conn.execute(
            "update inbox_items set status = 'pending', updated_at = now() where status = 'processing'"
        )
    if failed.rowcount or requeued.rowcount:
        log.info("recovered stuck items: %d requeued, %d failed", requeued.rowcount, failed.rowcount)


async def run(stop: asyncio.Event) -> None:
    """Work through the queue until `stop` is set. The item in progress is finished first."""
    poll_seconds = get_settings().worker_poll_seconds
    await recover_stuck()
    log.info("worker started")
    recover = False
    while not stop.is_set():
        try:
            if recover:
                # The item in progress when the error hit may still be marked `processing`.
                # Nothing is in progress now, so the startup recovery is safe to repeat.
                await recover_stuck()
                recover = False
            worked = await run_once()
        except Exception:
            # For example the database restarted. Stay alive and try again after a pause.
            log.exception("worker loop error")
            worked = False
            recover = True
        if not worked:
            # Queue empty: sleep until the next poll, but wake up at once when asked to stop.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
    log.info("worker stopped")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stop = asyncio.Event()
    # SIGTERM is what `docker stop` sends, SIGINT is Ctrl-C. Both ask for a clean stop: finish
    # the current item, then exit. If the process is killed before that, recover_stuck picks the
    # item up on the next start.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await db.open_pool(get_settings().database_url, max_size=2)
    try:
        await run(stop)
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
