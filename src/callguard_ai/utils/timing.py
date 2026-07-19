"""Timing utilities for latency measurement."""
from __future__ import annotations
import time
from contextlib import contextmanager
from typing import Generator


@contextmanager
def measure_ms() -> Generator[dict, None, None]:
    """Context manager that records elapsed milliseconds into a result dict."""
    result: dict = {}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)


def mock_latency(min_ms: int = 80, max_ms: int = 400) -> int:
    """Simulate realistic agent response latency. Returns ms slept."""
    import random
    ms = random.randint(min_ms, max_ms)
    time.sleep(ms / 1000)
    return ms
