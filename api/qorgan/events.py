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
from .models import Event, utcnow

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
    """Record an event; it is written with the caller's commit and reaches live subscribers only then.

    No flush here: all events of a request are inserted in the commit's single flush and announced
    with one NOTIFY round trip (see `_before_commit`).
    """
    payload = json.loads(json.dumps(payload, default=str, ensure_ascii=False))
    ev = Event(type=type_, payload=payload, created_at=utcnow())
    db.add(ev)
    db.info.setdefault("qorgan_events", []).append(ev)
    return ev


def _message(ev: Event) -> str:
    message = json.dumps({"id": ev.id, "type": ev.type, "payload": ev.payload, "created_at": ev.created_at}, default=str, ensure_ascii=False)
    if is_postgres and len(message.encode()) > NOTIFY_LIMIT:  # rare: send a stub, clients refetch from /v1/events
        stub = {"customer_id": ev.payload.get("customer_id"), "truncated": True}
        message = json.dumps({"id": ev.id, "type": ev.type, "payload": stub, "created_at": ev.created_at}, default=str)
    return message


@sa_event.listens_for(Session, "before_commit")
def _before_commit(session: Session) -> None:
    events = session.info.pop("qorgan_events", None)
    if not events:
        return
    session.flush()  # assigns event ids
    messages = [_message(ev) for ev in events]
    if is_postgres:
        # Delivered by Postgres on COMMIT, dropped on ROLLBACK.
        session.execute(
            text("SELECT pg_notify(:c, m) FROM unnest(CAST(:ms AS text[])) AS m"),
            {"c": CHANNEL, "ms": messages},
        )
    else:
        session.info.setdefault("qorgan_pending", []).extend(messages)


@sa_event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    for message in session.info.pop("qorgan_pending", []):
        bus.deliver(message)


@sa_event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop("qorgan_pending", None)
    session.info.pop("qorgan_events", None)


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
