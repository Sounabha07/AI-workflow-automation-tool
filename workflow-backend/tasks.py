import asyncio
import logging
import time

import blocks  # noqa: F401 -- importing this registers every block
import engine
import engine.triggers
from blocks.base import FatalError, RetryableError
from blocks.registry import get_block_class
from celery_app import celery_app
from retry import compute_backoff_seconds

logger = logging.getLogger(__name__)

# Retries for infrastructure errors (say, the database restarting) before the
# block has run. They share the task's retry count with the block's own budget.
SETUP_MAX_RETRIES = 3
# Waits between attempts to save a finished block's result.
SAVE_RETRY_DELAYS = (1, 2, 4)


def _save_result(handler, *args) -> None:
    """Saves a finished block, retrying only the save so the block itself
    doesn't run again. Repeating is safe: only the first finish counts. If
    every attempt fails, the sweeper eventually fails the stuck block."""
    for delay in SAVE_RETRY_DELAYS:
        try:
            asyncio.run(handler(*args))
            return
        except Exception:
            logger.exception("Could not save the result of a block; retrying in %ss", delay)
            time.sleep(delay)
    asyncio.run(handler(*args))


@celery_app.task(bind=True, max_retries=None)  # per-block max_retries enforced manually
def execute_block_task(self, run_id: str, block_id: str) -> None:
    attempts = self.request.retries + 1
    redelivered = bool((self.request.delivery_info or {}).get("redelivered"))

    try:
        if not asyncio.run(engine.claim_block(run_id, block_id, attempts > 1 or redelivered)):
            return
        context = asyncio.run(engine.get_block_context(run_id, block_id))
        block_cls = get_block_class(context["block_type"])
        block = block_cls()
        if not asyncio.run(engine.mark_running(
            run_id, block_id, context["config"], getattr(block_cls, "schema", {})
        )):
            return  # already waiting or finished: a redelivered task
    except engine.RunVanishedError:
        # Deleted between the claim and here: nothing left to run.
        logger.info("Run %s was deleted; skipping block %s", run_id, block_id)
        return
    except ValueError as e:
        # An unresolvable {{ }} reference or unusable credential won't fix
        # itself on retry.
        _save_result(engine.handle_block_failure, run_id, block_id, str(e), False, attempts)
        return
    except Exception as e:
        # Nothing has run yet, so trying again is safe.
        logger.exception("Could not set up block %s of run %s", block_id, run_id)
        if self.request.retries >= SETUP_MAX_RETRIES:
            _save_result(
                engine.handle_block_failure, run_id, block_id, f"Unexpected error: {e}", False, attempts
            )
            return
        raise self.retry(exc=e, countdown=2 ** attempts, max_retries=SETUP_MAX_RETRIES)

    # Inject the REAL run_id/block_id into config -- this is what makes
    # FailNTimesBlock's per-run counter unique automatically, no manual
    # worker restarts needed between runs. This is a narrow, deliberate
    # engine convenience for test blocks; real block config must stay
    # user-authored only, per the project's design decisions.
    config = dict(context["config"])
    config["run_id"] = run_id
    config["block_id"] = block_id

    try:
        output = asyncio.run(block.execute(
            config, input_data=context["input_data"], credentials=context["credentials"]
        ))
    except RetryableError as e:
        if self.request.retries >= block_cls.max_retries:
            _save_result(engine.handle_block_failure, run_id, block_id, str(e), True, attempts)
            return
        delay = compute_backoff_seconds(
            attempt=self.request.retries,
            base=block_cls.retry_backoff_base_seconds,
            cap=block_cls.retry_backoff_cap_seconds,
        )
        if e.retry_after_seconds is not None:
            delay = max(delay, min(e.retry_after_seconds, block_cls.retry_backoff_cap_seconds))
        asyncio.run(engine.record_retry(run_id, block_id, self.request.retries + 1))
        raise self.retry(exc=e, countdown=delay, max_retries=block_cls.max_retries)
    except FatalError as e:
        _save_result(engine.handle_block_failure, run_id, block_id, str(e), False, attempts)
        return
    except Exception as e:
        # Logged without the config, which may hold sensitive values.
        logger.exception("Unexpected error in block %s of run %s", block_id, run_id)
        _save_result(engine.handle_block_failure, run_id, block_id, f"Unexpected error: {e}", False, attempts)
        return
    else:
        if getattr(block_cls, "waits_for_input", False):
            # Park it and return: no sleeping, no worker slot held.
            _save_result(engine.mark_waiting, run_id, block_id, output["timeout_seconds"])
        else:
            _save_result(engine.handle_block_success, run_id, block_id, output)


# Periodic tasks, scheduled by the beat service (see celery_app.beat_schedule).
# All are safe to run concurrently from several processes.

@celery_app.task(ignore_result=True)
def sweep_wait_timeouts() -> int:
    return asyncio.run(engine.sweep_wait_timeouts())


@celery_app.task(ignore_result=True)
def fire_due_schedules() -> list[str]:
    return asyncio.run(engine.triggers.fire_due_schedules())


@celery_app.task(ignore_result=True)
def sweep_stuck_blocks() -> None:
    asyncio.run(engine.sweep_stuck_blocks())
