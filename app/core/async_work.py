"""Offload sequential blocking work without closing its DB session mid-call."""
import asyncio


async def run_blocking(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The calling request owns the session; wait for the thread before its
        # dependency/finalizer may close that session. Never use it concurrently.
        try:
            await task
        except Exception:
            pass
        raise
