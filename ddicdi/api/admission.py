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
# A labelled code (Code, CodePosition, Category, Notation) costs ``CODE_COST``, and the
# data a build may read one unit per ``DATA_BYTES_PER_UNIT`` bytes (GitLab #12): a
# cell's text is held about four times over (row, element, JSON text, response).
# Turning a CDIF document into an RDF graph and validating it (Check, Save to QLever)
# takes several times the memory of the JSON: ``RDF_FACTOR`` (GitLab #10).
VARIABLE_COST = 4
CODE_COST = 1
DATA_BYTES_PER_UNIT = 1024
RDF_FACTOR = 4

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

# Statistics, categories and edits that rewrite data.csv (GitLab #13): their work
# grows with the upload, so only a few run at once, as for imports.
heavy = Budget(
    "statistics and edits",
    capacity=lambda: max(1, settings.max_concurrent_heavy),
)

# SHACL validations (Check, Save to QLever; GitLab #10). Each runs in a child process.
validations = Budget(
    "CDIF checks",
    capacity=lambda: max(1, settings.max_concurrent_validations),
)


# Reading a saved document back from QLever (download, Open; GitLab #18).
qlever_reads = Budget(
    "documents being read from QLever",
    capacity=lambda: max(1, settings.max_concurrent_qlever_reads),
)


class UploadLocks:
    """One exclusive slot per upload (GitLab #14): edits of an upload are
    read-modify-write cycles over meta.json and data.csv, so they take turns. Waiting
    is bounded like any other admission (a 503 beyond it) and holds no worker thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[str, tuple[Budget, int]] = {}

    @asynccontextmanager
    async def hold(self, file_id: str) -> AsyncIterator[None]:
        with self._lock:
            budget, refs = self._held.get(file_id) or (Budget("changes to this upload", capacity=lambda: 1), 0)
            self._held[file_id] = (budget, refs + 1)
        try:
            async with budget.slot():
                yield
        finally:
            with self._lock:
                budget, refs = self._held[file_id]
                if refs <= 1:
                    del self._held[file_id]
                else:
                    self._held[file_id] = (budget, refs - 1)


uploads = UploadLocks()
