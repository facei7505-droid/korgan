"""In-process pub/sub for live dashboards (SSE) + persistent audit log.

Single-process by design for the MVP; swap for Redis/NATS when scaling out.
"""
import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session

from .models import Event


class Bus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _fanout(self, message: str) -> None:
        for q in list(self._subs):
            if q.full():
                q.get_nowait()
            q.put_nowait(message)

    def publish(self, message: dict[str, Any]) -> None:
        """Thread-safe: may be called from sync endpoints running in the threadpool."""
        data = json.dumps(message, default=str, ensure_ascii=False)
        if self._loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._fanout(data)
        else:
            self._loop.call_soon_threadsafe(self._fanout, data)


bus = Bus()


def emit(db: Session, type_: str, payload: dict[str, Any]) -> Event:
    """Persist an event and push it to live subscribers. Caller commits."""
    payload = json.loads(json.dumps(payload, default=str, ensure_ascii=False))
    ev = Event(type=type_, payload=payload)
    db.add(ev)
    db.flush()
    bus.publish({"id": ev.id, "type": type_, "payload": payload, "created_at": ev.created_at})
    return ev
