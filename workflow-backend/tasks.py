import asyncio
import logging

import blocks  # noqa: F401 -- importing this registers every block
import engine
from blocks.base import FatalError, RetryableError
from blocks.registry import get_block_class
from celery_app import celery_app
from retry import compute_backoff_seconds

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=None)  # per-block max_retries enforced manually
def execute_block_task(self, run_id: str, block_id: str) -> None:
    if asyncio.run(engine.is_run_failed(run_id)):
        return

    attempts = self.request.retries + 1

    try:
        context = asyncio.run(engine.get_block_context(run_id, block_id))
    except ValueError as e:
        # An unresolvable {{ }} reference won't fix itself on retry.
        asyncio.run(engine.handle_block_failure(run_id, block_id, str(e), False, attempts))
        return

    block_cls = get_block_class(context["block_type"])
    block = block_cls()

    asyncio.run(engine.mark_running(
        run_id, block_id, context["config"], getattr(block_cls, "schema", {})
    ))

    # Inject the REAL run_id/block_id into config -- this is what makes
    # FailNTimesBlock's per-run counter unique automatically, no manual
    # worker restarts needed between runs. This is a narrow, deliberate
    # engine convenience for test blocks; real block config must stay
    # user-authored only, per the project's design decisions.
    config = dict(context["config"])
    config["run_id"] = run_id
    config["block_id"] = block_id

    try:
        output = asyncio.run(block.execute(config, input_data={}))
    except RetryableError as e:
        if self.request.retries >= block_cls.max_retries:
            asyncio.run(engine.handle_block_failure(run_id, block_id, str(e), True, attempts))
            return
        delay = compute_backoff_seconds(
            attempt=self.request.retries,
            base=block_cls.retry_backoff_base_seconds,
            cap=block_cls.retry_backoff_cap_seconds,
        )
        asyncio.run(engine.record_retry(run_id, block_id, self.request.retries + 1))
        raise self.retry(exc=e, countdown=delay, max_retries=block_cls.max_retries)
    except FatalError as e:
        asyncio.run(engine.handle_block_failure(run_id, block_id, str(e), False, attempts))
        return
    except Exception as e:
        # Logged without the config, which may hold sensitive values.
        logger.exception("Unexpected error in block %s of run %s", block_id, run_id)
        asyncio.run(engine.handle_block_failure(
            run_id, block_id, f"Unexpected error: {e}", False, attempts
        ))
        return
    else:
        asyncio.run(engine.handle_block_success(run_id, block_id, output))
