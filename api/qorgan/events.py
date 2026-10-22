"""Live events for dashboards and guardian phones (SSE) + persistent audit log.

Delivery is transactional: subscribers only ever see events whose transaction committed.
- PostgreSQL: `pg_notify` inside the transaction; Postgres delivers it on COMMIT and drops it on
  ROLLBACK. Every API worker LISTENs, so SSE clients get events from any worker/instance.
- SQLite (dev/tests): an in-process fan-out after commit.
"""
import asyncio
import json
import logging
import threading
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import engine, is_postgres
from .models import Event

log = logging.getLogger("qorgan.events")
CHANNEL = "qorgan_events"
NOTIFY_LIMIT = 7900  # Postgres NOTIFY payload limit is 8000 bytes


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

    def deliver(self, message: str) -> None:
        """Thread-safe hand-off to the event loop that serves SSE clients."""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._fanout(message)
        else:
            self._loop.call_soon_threadsafe(self._fanout, message)


bus = Bus()


def emit(db: Session, type_: str, payload: dict[str, Any]) -> Event:
    """Persist an event; it reaches live subscribers when (and only if) the caller commits."""
    payload = json.loads(json.dumps(payload, default=str, ensure_ascii=False))
    ev = Event(type=type_, payload=payload)
    db.add(ev)
    db.flush()
    message = json.dumps({"id": ev.id, "type": type_, "payload": payload, "created_at": ev.created_at}, default=str, ensure_ascii=False)
    if is_postgres:
        if len(message.encode()) > NOTIFY_LIMIT:  # rare: send a stub, clients refetch from /v1/events
            message = json.dumps({"id": ev.id, "type": type_, "payload": {"customer_id": payload.get("customer_id"), "truncated": True}, "created_at": str(ev.created_at)})
        db.execute(text("SELECT pg_notify(:c, :m)"), {"c": CHANNEL, "m": message})
    else:
        db.info.setdefault("qorgan_pending", []).append(message)
    return ev


@sa_event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    for message in session.info.pop("qorgan_pending", []):
        bus.deliver(message)


@sa_event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop("qorgan_pending", None)


def start_listener(stop: threading.Event) -> threading.Thread | None:
    """Postgres only: forward NOTIFYs from any worker to this worker's SSE subscribers."""
    if not is_postgres:
        return None
    import psycopg

    dsn = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)

    def run() -> None:
        while not stop.is_set():
            try:
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    while not stop.is_set():
                        for n in conn.notifies(timeout=1.0):
                            bus.deliver(n.payload)
            except Exception:
                log.exception("event listener lost connection, reconnecting")
                stop.wait(2)

    t = threading.Thread(target=run, name="qorgan-listen", daemon=True)
    t.start()
    return t
