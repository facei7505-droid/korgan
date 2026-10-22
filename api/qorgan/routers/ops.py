import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..events import bus
from ..intel.extract import SCHEME_LABELS
from ..models import Case, Event, Indicator, Transfer
from ..risk.model import get_model
from ..security import require

router = APIRouter(prefix="/v1", tags=["ops"])


@router.get("/events", dependencies=[require("bank")])
def recent_events(limit: int = 100, type: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    q = select(Event).order_by(Event.id.desc()).limit(min(limit, 1000))
    if type:
        q = q.where(Event.type == type)
    return [{"id": e.id, "type": e.type, "payload": e.payload, "created_at": e.created_at} for e in db.scalars(q)]


@router.get("/events/stream", dependencies=[require("bank", "bot")])
async def stream(request: Request, customer_id: str | None = None) -> StreamingResponse:
    """Server-Sent Events. EventSource cannot set headers, so `?key=` is accepted here.

    `customer_id` limits the stream to one customer's events (what a customer or guardian device
    should subscribe with), so one person's alerts never reach another person's screen.
    """
    q = bus.subscribe()

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    if customer_id and not _belongs(msg, customer_id):
                        continue
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _belongs(msg: str, customer_id: str) -> bool:
    data = json.loads(msg)
    return data.get("type") == "demo.reset" or (data.get("payload") or {}).get("customer_id") == customer_id


@router.get("/model", dependencies=[require("bank")])
def model_card() -> dict:
    return get_model().card()


@router.get("/stats", dependencies=[require("bank")])
def stats(db: Session = Depends(get_db)) -> dict:
    by_status = dict(db.execute(select(Transfer.status, func.count()).group_by(Transfer.status)).all())
    prevented = db.scalar(select(func.coalesce(func.sum(Transfer.amount), 0)).where(Transfer.status == "cancelled")) or 0
    held = db.scalar(select(func.coalesce(func.sum(Transfer.amount), 0)).where(Transfer.status == "held")) or 0
    by_kind = dict(db.execute(select(Indicator.kind, func.count()).group_by(Indicator.kind)).all())
    schemes = db.execute(select(Case.scheme, func.count()).group_by(Case.scheme).order_by(func.count().desc())).all()
    return {
        "transfers": by_status, "total_transfers": sum(by_status.values()),
        "prevented_amount": float(prevented), "held_amount": float(held),
        "indicators": by_kind, "total_indicators": sum(by_kind.values()),
        "cases": sum(n for _, n in schemes),
        "schemes": [{"scheme": s, "label": SCHEME_LABELS.get(s, s), "count": n} for s, n in schemes],
        "model_version": get_model().version,
    }
