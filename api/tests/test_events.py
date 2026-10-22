"""Live events: delivered only after commit, in order, once per event (SQLite and Postgres paths)."""
import asyncio
import json

from qorgan.db import SessionLocal
from qorgan.events import bus, emit
from qorgan.seed import DEMO_CUSTOMER, DEMO_DROP_CARD

from .conftest import ADMIN, BANK


def _collect(client, q, keep, until: set[str], timeout: float = 5.0) -> list[dict]:
    """Messages matching `keep`, in arrival order, until one of each type in `until` has arrived.

    On Postgres, events of earlier tests can still be in flight through LISTEN, hence the filter.
    """

    async def run() -> list[dict]:
        got: list[dict] = []
        while not until <= {m["type"] for m in got}:
            m = json.loads(await asyncio.wait_for(q.get(), timeout))
            if keep(m):
                got.append(m)
        return got

    return client.portal.call(run)


def test_score_publishes_committed_events_in_order(client):
    q = bus.subscribe()
    try:
        res = client.post("/v1/transfers/score", headers=BANK, json={
            "customer_id": DEMO_CUSTOMER, "amount": 50000, "recipient": {"kind": "card", "value": DEMO_DROP_CARD},
        }).json()
        assert res["transfer"]["decision"] == "block"
        tid = res["transfer"]["id"]
        mine = lambda m: tid in (m["payload"].get("id"), m["payload"].get("transfer_id"))  # noqa: E731
        msgs = _collect(client, q, mine, until={"transfer.scored", "guardian.alert"})
    finally:
        bus.unsubscribe(q)
    assert [m["type"] for m in msgs] == ["transfer.scored", "guardian.alert"]
    assert msgs[0]["id"] < msgs[1]["id"]
    assert msgs[0]["payload"]["id"] == res["transfer"]["id"]
    stored = {e["id"] for e in client.get("/v1/events?limit=10", headers=ADMIN).json()}
    assert {m["id"] for m in msgs} <= stored


def test_rolled_back_events_are_never_published(client):
    q = bus.subscribe()
    try:
        with SessionLocal() as db:
            emit(db, "test.ghost", {"customer_id": DEMO_CUSTOMER})
            db.rollback()
        with SessionLocal() as db:
            emit(db, "test.marker", {"customer_id": DEMO_CUSTOMER})
            db.commit()
        msgs = _collect(client, q, lambda m: m["type"].startswith("test."), until={"test.marker"})
    finally:
        bus.unsubscribe(q)
    assert [m["type"] for m in msgs] == ["test.marker"]
