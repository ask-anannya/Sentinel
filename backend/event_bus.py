"""
Thread-safe in-memory event bus for broadcasting real-time scan progress to SSE clients.
Fan-out pattern: one emitter (worker threads) → many subscribers (SSE connections).
"""

import asyncio
import logging
from datetime import datetime
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class ScanEventBus:
    def __init__(self) -> None:
        # scan_id -> list of asyncio.Queue (one per SSE subscriber)
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the running event loop. Called once at app startup."""
        self._loop = loop

    # ------------------------------------------------------------------
    # Emit — callable from ThreadPoolExecutor workers (thread-safe)
    # ------------------------------------------------------------------

    def emit(
        self,
        stream_id: str | None,
        tool: str,
        message: str,
        status: str,
        agent_index: int = 0,
        step_index: int | None = None,
        screenshot: str | None = None,
    ) -> None:
        """
        Broadcast an event to all subscribers for stream_id (scan_id or violation_id).
        Thread-safe: uses call_soon_threadsafe to schedule onto the event loop.
        """
        if not self._loop:
            return

        event = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "tool": tool,
            "message": message,
            "status": status,
            "agent_index": agent_index,
            "step_index": step_index,
            "screenshot": screenshot,
        }

        def _put() -> None:
            queues = self._subscribers.get(stream_id, [])
            for q in queues:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("SSE queue full for stream %s, dropping event", stream_id)

        self._loop.call_soon_threadsafe(_put)

    # ------------------------------------------------------------------
    # Subscribe — async generator for SSE endpoint
    # ------------------------------------------------------------------

    async def subscribe(self, stream_id: str) -> AsyncGenerator[dict, None]:
        """Yield events for stream_id as they arrive. Yields None sentinel on completion."""
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(stream_id, []).append(q)
        logger.debug("SSE subscriber attached for stream %s", stream_id)
        try:
            while True:
                event = await q.get()
                if event is None:  # sentinel — stream finished
                    break
                yield event
        finally:
            queues = self._subscribers.get(stream_id, [])
            if q in queues:
                queues.remove(q)
            if not queues and stream_id in self._subscribers:
                del self._subscribers[stream_id]
            logger.debug("SSE subscriber detached for stream %s", stream_id)

    def close(self, stream_id: str) -> None:
        """Send sentinel to all subscribers, signalling stream completion."""
        if not self._loop:
            return

        def _close() -> None:
            for q in self._subscribers.get(stream_id, []):
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass

        self._loop.call_soon_threadsafe(_close)


# Module-level singleton
event_bus = ScanEventBus()
