from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..events import emit
from ..intel.extract import fingerprint, to_entity
from ..models import Customer, Guardian, KnownRecipient, Transfer
from ..notify import telegram_guardian_alert
from ..risk.engine import Behavior, assess
from ..schemas import ChallengeAnswer, GuardianAnswer, ScoreRequest
from ..security import require

router = APIRouter(prefix="/v1/transfers", tags=["transfers"])

CUSTOMER_MESSAGES = {
    "allow": None,
    "challenge": {
        "title": "Минутку. Вам сейчас кто-то диктует, что делать?",
        "body": "Банк, полиция и КНБ никогда не просят переводить деньги на «безопасный счёт» и не диктуют реквизиты по телефону.",
    },
    "hold": {
        "title": "Перевод приостановлен на {hold} минут",
        "body": "Вы разговариваете с незнакомым номером и переводите крупную сумму. Так действуют мошенники. Положите трубку и перезвоните в банк по номеру на карте. Мы сообщили вашему доверенному человеку.",
    },
    "block": {
        "title": "Перевод остановлен: получатель связан с мошенниками",
        "body": "Эти реквизиты уже использовались в мошеннических схемах. Не переводите деньги, положите трубку. Мы сообщили вашему доверенному человеку.",
    },
}


def serialize(t: Transfer) -> dict:
    return {
        "id": t.id, "customer_id": t.customer_id, "amount": t.amount, "recipient": t.recipient_masked,
        "recipient_kind": t.recipient_kind, "score": t.score, "decision": t.decision, "status": t.status,
        "reasons": t.reasons, "features": t.features, "hold_until": t.hold_until, "resolution": t.resolution,
        "created_at": t.created_at,
    }


def _remember_recipient(db: Session, t: Transfer) -> None:
    kr = db.scalar(select(KnownRecipient).where(KnownRecipient.customer_id == t.customer_id, KnownRecipient.recipient_hash == t.recipient_hash))
    if kr:
        kr.count += 1
    else:
        db.add(KnownRecipient(customer_id=t.customer_id, recipient_hash=t.recipient_hash))


def _get(db: Session, transfer_id: str) -> Transfer:
    t = db.get(Transfer, transfer_id)
    if not t:
        raise HTTPException(404, "transfer not found")
    return t


def _notify_guardians(db: Session, customer: Customer, t: Transfer, call: dict | None) -> list[str]:
    notified = []
    for g in customer.guardians:
        if t.decision == "hold" and t.amount < g.min_amount:
            continue
        call_txt = ""
        if call:
            call_txt = f" во время {'идущего' if call['active'] else 'недавнего'} звонка ({call['channel']}, {call['minutes']} мин) с {'незнакомым' if not call['in_contacts'] else 'известным'} номером"
        text = f"⚠️ {customer.name} переводит <b>{int(t.amount):,} ₸</b>{call_txt}. Перевод приостановлен. Это она? Позвоните ей."
        payload = {
            "guardian_id": g.id, "guardian_name": g.name, "customer_id": customer.id, "customer_name": customer.name,
            "transfer_id": t.id, "amount": t.amount, "recipient": t.recipient_masked, "score": t.score,
            "decision": t.decision, "reasons": t.reasons[:3], "call": call, "text": text.replace("<b>", "").replace("</b>", ""),
        }
        emit(db, "guardian.alert", payload)
        if g.telegram_chat_id:
            telegram_guardian_alert(g.telegram_chat_id, text, t.id)
        notified.append(g.id)
    return notified


@router.post("/score", dependencies=[require("bank")])
def score_transfer(req: ScoreRequest, db: Session = Depends(get_db)) -> dict:
    """Score an outgoing transfer before it is executed. Target latency < 50 ms."""
    customer = db.get(Customer, req.customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    ent = to_entity(req.recipient.kind, req.recipient.value)
    if not ent:
        raise HTTPException(422, f"invalid {req.recipient.kind}")
    rhash = fingerprint(ent.kind, ent.value)

    a = assess(db, customer, req.amount, ent.kind, rhash, Behavior(**req.behavior.model_dump()), req.local_hour)
    status = {"allow": "completed", "challenge": "pending_challenge", "hold": "held", "block": "held"}[a.decision]
    hold_until = None
    if a.decision == "hold":
        hold_until = datetime.now(timezone.utc) + timedelta(minutes=settings.hold_minutes)
    t = Transfer(
        customer_id=customer.id, amount=req.amount, recipient_kind=ent.kind, recipient_hash=rhash,
        recipient_masked=ent.display, score=a.score, decision=a.decision, status=status,
        reasons=a.reasons, features=a.features, hold_until=hold_until,
    )
    db.add(t)
    db.flush()
    if status == "completed":
        _remember_recipient(db, t)
    emit(db, "transfer.scored", {**serialize(t), "customer_name": customer.name, "call": a.call, "registry_hits": a.registry_hits})
    notified = _notify_guardians(db, customer, t, a.call) if a.decision in ("hold", "block") else []
    db.commit()

    msg = CUSTOMER_MESSAGES[a.decision]
    if msg:
        msg = {k: v.format(hold=settings.hold_minutes) for k, v in msg.items()}
    return {
        "transfer": serialize(t), "call": a.call, "registry_hits": a.registry_hits,
        "customer_message": msg, "guardians_notified": notified,
    }


@router.post("/{transfer_id}/challenge", dependencies=[require("bank")])
def answer_challenge(transfer_id: str, body: ChallengeAnswer, db: Session = Depends(get_db)) -> dict:
    t = _get(db, transfer_id)
    if t.status != "pending_challenge":
        raise HTTPException(409, f"transfer is {t.status}")
    if body.dictated:
        t.status, t.resolution = "cancelled", "customer_confirmed_dictation"
    else:
        t.status, t.resolution = "completed", "customer_denied_dictation"
        _remember_recipient(db, t)
    emit(db, "transfer.updated", serialize(t))
    db.commit()
    return serialize(t)


@router.post("/{transfer_id}/guardian", dependencies=[require("bank", "bot")])
def guardian_decision(transfer_id: str, body: GuardianAnswer, db: Session = Depends(get_db)) -> dict:
    t = _get(db, transfer_id)
    if t.status != "held":
        raise HTTPException(409, f"transfer is {t.status}")
    if body.approve and t.decision == "block":
        # Registry hits cannot be overridden by a guardian; the bank's fraud team must review.
        t.resolution = "guardian_approved_pending_bank_review"
    elif body.approve:
        t.status, t.resolution = "released", "guardian_approved"
        _remember_recipient(db, t)
    else:
        t.status, t.resolution = "cancelled", "guardian_rejected"
    emit(db, "transfer.updated", {**serialize(t), "by": "guardian", "guardian_id": body.guardian_id})
    db.commit()
    return serialize(t)


@router.post("/{transfer_id}/cancel", dependencies=[require("bank")])
def cancel(transfer_id: str, db: Session = Depends(get_db)) -> dict:
    t = _get(db, transfer_id)
    if t.status in ("completed", "released", "cancelled"):
        raise HTTPException(409, f"transfer is {t.status}")
    t.status, t.resolution = "cancelled", "customer_cancelled"
    emit(db, "transfer.updated", serialize(t))
    db.commit()
    return serialize(t)


@router.get("", dependencies=[require("bank")])
def list_transfers(limit: int = 50, customer_id: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    q = select(Transfer).order_by(Transfer.created_at.desc()).limit(min(limit, 500))
    if customer_id:
        q = q.where(Transfer.customer_id == customer_id)
    return [serialize(t) for t in db.scalars(q)]


@router.get("/{transfer_id}", dependencies=[require("bank")])
def get_transfer(transfer_id: str, db: Session = Depends(get_db)) -> dict:
    return serialize(_get(db, transfer_id))
