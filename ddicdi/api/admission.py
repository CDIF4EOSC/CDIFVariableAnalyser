"""Admission control for heavy requests (imports, document builds, enrichment).

A :class:`Budget` admits work while its total cost stays within a capacity. Requests
that do not fit wait in the event loop (``asyncio.sleep`` polling), never on a worker
thread, so a queue of waiting uploads cannot starve the thread pool that every sync
route, dependency and file response needs. Both the number of waiters and the time
they wait are bounded; a request over either limit gets a prompt 503.

The state is guarded by a thread lock, not an asyncio primitive, so one budget works
across event loops (the test clients each run their own).
"""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

from fastapi import HTTPException

from ..config import settings

POLL_SECONDS = 0.05


class Budget:
    """A shared allowance of ``capacity()`` cost units held by at most ``max_holders()``.

    The limits are callables so they follow ``settings`` at the time of each request.
    A capacity of 0 or less switches the cost limit off. A single request costing more
    than the capacity is clamped to it, so it runs alone rather than never.
    """

    def __init__(
        self,
        what: str,
        capacity: Callable[[], int],
        *,
        max_holders: Callable[[], int] = lambda: 0,
        max_waiters: Callable[[], int] = lambda: settings.max_queued_requests,
        timeout: Callable[[], float] = lambda: settings.queue_timeout,
    ) -> None:
        self.what = what
        self._capacity = capacity
        self._max_holders = max_holders
        self._max_waiters = max_waiters
        self._timeout = timeout
        self._lock = threading.Lock()
        self.used = 0
        self.holders = 0
        self.waiters = 0

    def _cost(self, cost: int) -> int:
        capacity = self._capacity()
        cost = max(int(cost), 1)
        return min(cost, capacity) if capacity > 0 else cost

    def try_take(self, cost: int) -> bool:
        capacity, holders = self._capacity(), self._max_holders()
        with self._lock:
            if holders > 0 and self.holders >= holders:
                return False
            if capacity > 0 and self.used + cost > capacity:
                return False
            self.used += cost
            self.holders += 1
            return True

    def release(self, cost: int) -> None:
        with self._lock:
            self.used -= cost
            self.holders -= 1

    def _busy(self) -> HTTPException:
        return HTTPException(
            status_code=503,
            detail=f"The server is busy with other {self.what}; try again shortly",
            headers={"Retry-After": "10"},
        )

    @asynccontextmanager
    async def slot(self, cost: int = 1) -> AsyncIterator[None]:
        """Hold ``cost`` units for the body of the ``async with``; 503 when none come free."""
        cost = self._cost(cost)
        if not self.try_take(cost):
            with self._lock:
                if self.waiters >= max(self._max_waiters(), 0):
                    raise self._busy()
                self.waiters += 1
            try:
                deadline = time.monotonic() + max(self._timeout(), 0)
                while not self.try_take(cost):
                    if time.monotonic() >= deadline:
                        raise self._busy()
                    await asyncio.sleep(POLL_SECONDS)
            finally:
                with self._lock:
                    self.waiters -= 1
        try:
            yield
        finally:
            self.release(cost)


# Imports run qsv for up to ``qsv_timeout`` per call; at most ``max_concurrent_imports``.
imports = Budget(
    "imports",
    capacity=lambda: max(1, settings.max_concurrent_imports),
)

# Document builds (generate, output, convert). Each build holds its estimated size in
# data cells: rows x variables, plus ``VARIABLE_COST`` per variable for the metadata
# (measured at ~15.7 KB per variable against ~5.2 KB per cell). The total of all
# builds in flight stays within ``max_output_cells``, which is sized so the worst case
# fits the instance; ``max_concurrent_builds`` also caps how many run at once.
VARIABLE_COST = 4

builds = Budget(
    "document builds",
    capacity=lambda: settings.max_output_cells,
    max_holders=lambda: max(1, settings.max_concurrent_builds),
)

# AI enrichment: each request fans out to many n8n/LLM calls, so only a few run at once.
enrichments = Budget(
    "AI enrichment requests",
    capacity=lambda: max(1, settings.max_concurrent_enrich),
)
