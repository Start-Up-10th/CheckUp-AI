"""Serialize native inference without blocking the HTTP event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, TypeVar

Result = TypeVar("Result")


async def _drain(
    future: asyncio.Future[Result],
    on_cancel: Callable[[Result], None] | None = None,
) -> Result:
    """Finish accepted work before cancellation releases its input buffers.

    A fresh shield is needed after every cancellation: the cancelled shield cannot
    be reused, but the underlying future must never be cancelled or abandoned.
    Cleanup callbacks run synchronously on the caller's event loop after native
    work finishes, including when a second cancellation arrives while draining.
    """
    cancellation = None
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError as error:
            cancellation = error
        except BaseException:
            # Retrieve the native exception below, preserving request cancellation
            # if that happened first. Calling result() also consumes the exception.
            if not future.done():
                raise

    try:
        result = future.result()
    except BaseException:
        if cancellation is not None:
            raise cancellation from None
        raise
    if cancellation is not None:
        try:
            if on_cancel is not None:
                on_cancel(result)
        finally:
            raise cancellation
    return result


class InferenceExecutor:
    """One lifespan-owned native worker with FIFO submissions.

    Callers bound admission and own input-buffer cleanup. Once run() is submitted,
    its caller cannot leave run() until native code stops touching those buffers.
    on_cancel disposes a successful result that cancellation prevents returning to
    the caller (for example, a decoded image or an embedding).
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face-inference")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: set[asyncio.Future[Any]] = set()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    def _current_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("InferenceExecutor must be used from one event loop")
        return loop

    async def run(
        self,
        function: Callable[..., Result],
        *args: Any,
        on_cancel: Callable[[Result], None] | None = None,
    ) -> Result:
        loop = self._current_loop()
        if self._closing:
            raise RuntimeError("InferenceExecutor is closed")
        future = loop.run_in_executor(self._executor, partial(function, *args))
        self._pending.add(future)
        try:
            return await _drain(future, on_cancel)
        finally:
            self._pending.discard(future)

    async def _drain_and_shutdown(self) -> None:
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
        # Joining even an idle worker is blocking. Use the loop's separate default
        # executor so the owned inference thread cannot try to join itself.
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=False)

    async def close(self) -> None:
        """Reject new work, drain accepted jobs, and join the owned worker once."""
        loop = self._current_loop()
        if self._close_task is None:
            self._closing = True
            self._close_task = loop.create_task(self._drain_and_shutdown())
        await _drain(self._close_task)
