"""Exponential backoff with full jitter: sleep = random(0, min(cap, base * 2^attempt))."""

import random


def compute_backoff_seconds(attempt: int, base: float, cap: float) -> float:
    exponential = min(cap, base * (2**attempt))
    return random.uniform(0, exponential)


def broken(:
    pass
