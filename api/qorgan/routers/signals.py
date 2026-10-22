from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..events import emit
from ..intel.extract import fingerprint, mask_phone, norm_phone
from ..models import CallSignal, Customer, Guardian, utcnow
from ..schemas import CallStart, CustomerIn, GuardianIn, GuardianLink
from ..security import require

router = APIRouter(prefix="/v1", tags=["signals & customers"])


def call_out(c: CallSignal) -> dict:
    return {
        "id": c.id, "customer_id": c.customer_id, "source": c.source, "channel": c.channel,
        "counterparty": c.counterparty_masked, "in_contacts": c.in_contacts,
        "spoof_suspected": c.spoof_suspected, "mass_caller": c.mass_caller,
        "started_at": c.started_at, "ended_at": c.ended_at,
    }


@router.post("/signals/call", dependencies=[require("bank")])
def call_started(body: CallStart, db: Session = Depends(get_db)) -> dict:
    """Bank app (CXCallObserver on iOS / TelephonyCallback on Android) or telco reports a call start.

    Only metadata is accepted. The number is HMAC-hashed immediately.
    """
    if not db.get(Customer, body.customer_id):
        raise HTTPException(404, "customer not found")
    phone = norm_phone(body.counterparty) if body.counterparty else None
    c = CallSignal(
        customer_id=body.customer_id, source=body.source, channel=body.channel,
        counterparty_hash=fingerprint("phone", phone) if phone else None,
        counterparty_masked=mask_phone(phone) if phone else None,
        in_contacts=body.in_contacts, spoof_suspected=body.spoof_suspected, mass_caller=body.mass_caller,
    )
    db.add(c)
    db.flush()
    emit(db, "call.started", call_out(c))
    db.commit()
    return call_out(c)


@router.post("/signals/call/{call_id}/end", dependencies=[require("bank")])
def call_ended(call_id: str, db: Session = Depends(get_db)) -> dict:
    c = db.get(CallSignal, call_id)
    if not c:
        raise HTTPException(404, "call not found")
    if c.ended_at is None:
        c.ended_at = utcnow()
        emit(db, "call.ended", call_out(c))
        db.commit()
    return call_out(c)


@router.get("/customers/{customer_id}/calls", dependencies=[require("bank")])
def active_calls(customer_id: str, db: Session = Depends(get_db)) -> list[dict]:
    q = select(CallSignal).where(CallSignal.customer_id == customer_id).order_by(CallSignal.started_at.desc()).limit(20)
    return [call_out(c) for c in db.scalars(q)]


def customer_out(c: Customer) -> dict:
    return {
        "id": c.id, "name": c.name, "age": c.age, "typical_amount": c.typical_amount,
        "guardians": [
            {"id": g.id, "name": g.name, "relation": g.relation, "phone": g.phone_masked,
             "telegram_linked": bool(g.telegram_chat_id), "link_code": g.link_code, "min_amount": g.min_amount}
            for g in c.guardians
        ],
    }


@router.post("/customers", dependencies=[require("bank")])
def create_customer(body: CustomerIn, db: Session = Depends(get_db)) -> dict:
    c = Customer(**body.model_dump())
    db.add(c)
    db.commit()
    return customer_out(c)


@router.get("/customers/{customer_id}", dependencies=[require("bank")])
def get_customer(customer_id: str, db: Session = Depends(get_db)) -> dict:
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "customer not found")
    return customer_out(c)


@router.post("/customers/{customer_id}/guardians", dependencies=[require("bank")])
def add_guardian(customer_id: str, body: GuardianIn, db: Session = Depends(get_db)) -> dict:
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "customer not found")
    phone = norm_phone(body.phone) if body.phone else None
    g = Guardian(customer_id=c.id, name=body.name, relation=body.relation, phone_masked=mask_phone(phone) if phone else "", min_amount=body.min_amount)
    db.add(g)
    db.commit()
    db.refresh(c)
    return customer_out(c)


@router.post("/guardians/link", dependencies=[require("bot")])
def link_guardian(body: GuardianLink, db: Session = Depends(get_db)) -> dict:
    """Guardian sends /link CODE to the Telegram bot to receive alerts there."""
    g = db.scalar(select(Guardian).where(Guardian.link_code == body.code.strip().upper()))
    if not g:
        raise HTTPException(404, "unknown code")
    g.telegram_chat_id = body.telegram_chat_id
    emit(db, "guardian.linked", {"guardian_id": g.id, "customer_id": g.customer_id, "name": g.name})
    db.commit()
    return {"guardian_id": g.id, "name": g.name, "customer_name": g.customer.name}
