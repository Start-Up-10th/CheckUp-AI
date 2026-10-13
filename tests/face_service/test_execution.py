from __future__ import annotations

import asyncio
import threading

import pytest

from face_execution import InferenceExecutor


def test_native_work_runs_in_fifo_order_on_one_thread_without_blocking_event_loop():
    async def scenario():
        executor = InferenceExecutor()
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        order = []
        threads = []

        def work(value):
            threads.append(threading.current_thread())
            order.append(value)
            if value == 0:
                loop.call_soon_threadsafe(started.set)
                assert release.wait(timeout=5)
            return value

        tasks = [asyncio.create_task(executor.run(work, 0))]
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            for value in (1, 2):
                tasks.append(asyncio.create_task(executor.run(work, value)))
                await asyncio.sleep(0)
            # Reaching this point while native work is still blocked also verifies
            # HTTP/heartbeat coroutines retain access to the event loop.
            assert order == [0]
            assert not any(task.done() for task in tasks)
            assert len(executor._pending) == 3
            release.set()
            assert await asyncio.gather(*tasks) == [0, 1, 2]
            assert order == [0, 1, 2]
            assert len(set(threads)) == 1
            assert threads[0] is not threading.current_thread()
            assert not executor._pending
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await executor.close()
        assert not threads[0].is_alive()

    asyncio.run(scenario())


@pytest.mark.parametrize("repeat_cancel", [False, True])
@pytest.mark.parametrize("native_failure", [False, True])
def test_cancellation_drains_native_work_before_result_and_input_cleanup(
    repeat_cancel, native_failure
):
    async def scenario():
        executor = InferenceExecutor()
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        source = bytearray(b"synthetic-input")
        output = bytearray(b"synthetic-output")
        cleanup_calls = []
        worker_reads = []

        def work():
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=5)
            worker_reads.append(bytes(source))
            if native_failure:
                raise ValueError("synthetic native failure")
            return output

        def cleanup(result):
            assert result is output
            cleanup_calls.append(threading.current_thread())
            result[:] = b"\0" * len(result)

        async def request():
            try:
                await executor.run(work, on_cancel=cleanup)
            finally:
                source[:] = b"\0" * len(source)

        task = asyncio.create_task(request())
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            task.cancel()
            await asyncio.sleep(0)
            if repeat_cancel:
                task.cancel()
                await asyncio.sleep(0)
            assert not task.done()
            assert source == b"synthetic-input"
            assert output == b"synthetic-output"
            assert not cleanup_calls
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
            assert worker_reads == [b"synthetic-input"]
            assert not any(source)
            assert cleanup_calls == ([] if native_failure else [threading.current_thread()])
            assert bool(any(output)) is native_failure
            assert not executor._pending
            # Cancellation and native failures do not poison the single worker.
            assert await executor.run(lambda: "next") == "next"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await executor.close()

    asyncio.run(scenario())


def test_cancelled_queued_job_still_finishes_and_disposes_its_result():
    async def scenario():
        executor = InferenceExecutor()
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        completed = []
        cleaned = []

        def blocked():
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=5)

        def queued():
            completed.append(True)
            return None

        first = asyncio.create_task(executor.run(blocked))
        second = None
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            second = asyncio.create_task(executor.run(queued, on_cancel=cleaned.append))
            await asyncio.sleep(0)
            second.cancel()
            await asyncio.sleep(0)
            assert not second.done() and not completed and not cleaned
            release.set()
            assert await first is None
            with pytest.raises(asyncio.CancelledError):
                await second
            assert completed == [True] and cleaned == [None]
        finally:
            release.set()
            await asyncio.gather(
                *([first, second] if second is not None else [first]), return_exceptions=True
            )
            await executor.close()

    asyncio.run(scenario())


def test_native_exceptions_propagate_and_normal_results_do_not_call_cancel_cleanup():
    async def scenario():
        executor = InferenceExecutor()
        cleaned = []

        def fail():
            raise ValueError("synthetic native failure")

        try:
            with pytest.raises(ValueError, match="synthetic native failure"):
                await executor.run(fail, on_cancel=cleaned.append)
            assert await executor.run(lambda: None, on_cancel=cleaned.append) is None
            assert not cleaned and not executor._pending
        finally:
            await executor.close()

    asyncio.run(scenario())


def test_result_cleanup_failure_preserves_request_cancellation():
    async def scenario():
        executor = InferenceExecutor()
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        cleaned = []

        def blocked():
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=5)
            return "result"

        def cleanup(result):
            cleaned.append(result)
            raise ValueError("synthetic cleanup failure")

        task = asyncio.create_task(executor.run(blocked, on_cancel=cleanup))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cleaned == ["result"]
            assert not executor._pending
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await executor.close()

    asyncio.run(scenario())


def test_close_rejects_submissions_drains_accepted_jobs_and_is_repeatable_when_cancelled():
    async def scenario():
        executor = InferenceExecutor()
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        order = []
        threads = []

        def work(value):
            threads.append(threading.current_thread())
            order.append(value)
            if value == 0:
                loop.call_soon_threadsafe(started.set)
                assert release.wait(timeout=5)
            return value

        jobs = [asyncio.create_task(executor.run(work, 0))]
        closes = []
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            jobs.append(asyncio.create_task(executor.run(work, 1)))
            await asyncio.sleep(0)
            closes.append(asyncio.create_task(executor.close()))
            await asyncio.sleep(0)
            with pytest.raises(RuntimeError, match="closed"):
                await executor.run(work, 2)
            closes.append(asyncio.create_task(executor.close()))
            await asyncio.sleep(0)
            closes[0].cancel()
            await asyncio.sleep(0)
            closes[0].cancel()
            await asyncio.sleep(0)
            assert order == [0]
            assert not any(task.done() for task in jobs + closes)
            release.set()
            assert await asyncio.gather(*jobs) == [0, 1]
            with pytest.raises(asyncio.CancelledError):
                await closes[0]
            await closes[1]
            await executor.close()
            assert order == [0, 1]
            assert not any(thread.is_alive() for thread in threads)
            assert not executor._pending
            with pytest.raises(RuntimeError, match="closed"):
                await executor.run(work, 3)
        finally:
            release.set()
            await asyncio.gather(*jobs, *closes, return_exceptions=True)
            await executor.close()

    asyncio.run(scenario())


def test_close_without_submissions_and_cross_loop_use():
    executor = InferenceExecutor()

    async def first_loop():
        await executor.close()
        await executor.close()

    asyncio.run(first_loop())

    async def another_loop():
        with pytest.raises(RuntimeError, match="one event loop"):
            await executor.run(lambda: None)
        with pytest.raises(RuntimeError, match="one event loop"):
            await executor.close()

    asyncio.run(another_loop())
