import asyncio
import threading
import time
import pytest
from app.core.async_work import run_blocking


def test_blocking_work_does_not_prevent_event_loop_progress():
    started, release = threading.Event(), threading.Event()

    def work():
        started.set()
        assert release.wait(1)
        return "done"

    async def run():
        task = asyncio.create_task(run_blocking(work))
        while not started.is_set():
            await asyncio.sleep(0)
        release.set()
        assert await task == "done"

    asyncio.run(run())


def test_cancellation_waits_for_worker_before_session_cleanup():
    completed = threading.Event()

    def work():
        time.sleep(0.03)
        completed.set()

    async def run():
        task = asyncio.create_task(run_blocking(work))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()

    asyncio.run(run())
