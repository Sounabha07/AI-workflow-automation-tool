from abc import ABC, abstractmethod
from typing import Any


class EngineError(Exception):
    """Base class for all engine/block errors."""


class RetryableError(EngineError):
    """A failure that might succeed if retried. retry_after_seconds is the
    server's own hint (e.g. Retry-After); the task waits at least that long,
    up to the block's backoff cap."""

    def __init__(self, message: str = "", retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class FatalError(EngineError):
    """A failure that will never succeed on retry."""


class BaseBlock(ABC):
    """
    Contract: execute(config, input_data, credentials) -> dict

    Retry policy is block-specific: a block type declares its own retry
    budget and backoff shape by overriding these class attributes. The
    Celery task wrapper reads them generically, without knowing anything
    about which block type they belong to.
    """

    max_retries: int = 3
    retry_backoff_base_seconds: float = 1.0
    retry_backoff_cap_seconds: float = 60.0

    @abstractmethod
    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError
