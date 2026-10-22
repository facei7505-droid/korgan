"""Scoring a transfer: features -> model -> hard rules -> decision."""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import CallSignal, Customer, Indicator, KnownRecipient
from .model import REASON_TEXT, get_model

CALL_WINDOW = timedelta(hours=3)
THRESHOLDS = {"challenge": 0.25, "hold": 0.6, "block": 0.85}


@dataclass
class Behavior:
    max_pause_ms: float = 0
    corrections: int = 0
    session_seconds: float = 0
    pasted_recipient: bool = False
    app_switches: int = 0

    def hesitation(self) -> float:
        return round(
            0.5 * min(self.max_pause_ms / 15000, 1)
            + 0.3 * min(self.corrections / 8, 1)
            + 0.2 * min(self.session_seconds / 240, 1),
            3,
        )


@dataclass
class Assessment:
    score: float
    decision: str
    reasons: list[dict]
    features: dict[str, float]
    call: dict | None = None
    registry_hits: list[dict] = field(default_factory=list)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def relevant_call(db: Session, customer_id: str, now: datetime) -> CallSignal | None:
    """The riskiest call that is ongoing or ended within CALL_WINDOW."""
    calls = db.scalars(
        select(CallSignal)
        .where(CallSignal.customer_id == customer_id)
        .where(or_(CallSignal.ended_at.is_(None), CallSignal.ended_at >= now - CALL_WINDOW))
        .order_by(CallSignal.started_at.desc())
    ).all()
    if not calls:
        return None
    return max(calls, key=lambda c: (c.ended_at is None, not c.in_contacts, _as_utc(c.started_at)))


def registry_lookup(db: Session, kind: str, value_hash: str) -> Indicator | None:
    return db.scalar(select(Indicator).where(Indicator.kind == kind, Indicator.value_hash == value_hash))


def assess(
    db: Session,
    customer: Customer,
    amount: float,
    recipient_kind: str,
    recipient_hash: str,
    behavior: Behavior,
    local_hour: int | None = None,
    now: datetime | None = None,
) -> Assessment:
    now = now or datetime.now(timezone.utc)
    call = relevant_call(db, customer.id, now)

    feats: dict[str, float] = {f: 0.0 for f in REASON_TEXT}
    call_info = None
    if call:
        started = _as_utc(call.started_at)
        ended = _as_utc(call.ended_at) if call.ended_at else None
        minutes = ((ended or now) - started).total_seconds() / 60
        since_end = 0.0 if ended is None else (now - ended).total_seconds() / 60
        feats.update(
            call_active=float(ended is None),
            unknown_caller=float(not call.in_contacts),
            call_minutes_log=math.log1p(max(minutes, 0)),
            recent_call_decay=1.0 if ended is None else math.exp(-since_end / 30),
            messenger_call=float(call.channel in {"whatsapp", "telegram", "voip"}),
            telco_risk=float(call.spoof_suspected or call.mass_caller),
        )
        call_info = {
            "active": ended is None,
            "channel": call.channel,
            "minutes": round(minutes, 1),
            "minutes_since_end": round(since_end, 1),
            "in_contacts": call.in_contacts,
            "counterparty": call.counterparty_masked,
        }

    known = db.scalar(
        select(KnownRecipient).where(
            KnownRecipient.customer_id == customer.id, KnownRecipient.recipient_hash == recipient_hash
        )
    )
    hour = local_hour if local_hour is not None else (now + timedelta(hours=5)).hour  # Asia/Almaty, UTC+5
    feats.update(
        recipient_new=float(known is None),
        amount_ratio_log=math.log(max(amount / max(customer.typical_amount, 1), 0.05)),
        elderly=float(customer.age >= 60),
        hesitation=behavior.hesitation(),
        pasted_recipient=float(behavior.pasted_recipient),
        app_switches=float(min(behavior.app_switches, 6)),
        night=float(hour >= 23 or hour < 6),
    )

    explained = get_model().explain(feats)
    score = explained.probability
    reasons = [
        {"code": f, "text": REASON_TEXT[f], "weight": round(c, 2)}
        for f, c in sorted(explained.contributions.items(), key=lambda kv: -kv[1])
        if c > 0.25 and feats[f] > 0
    ][:5]
    for r in reasons:
        if r["code"] == "unknown_caller" and feats["call_active"]:
            r["text"] = "Клиент прямо сейчас говорит с номером, которого нет в контактах"

    # Hard rules from threat intelligence (Apa, reports, other banks).
    hits: list[dict] = []
    rcpt_ind = registry_lookup(db, recipient_kind, recipient_hash)
    if rcpt_ind:
        hits.append({"what": "recipient", "indicator_id": rcpt_ind.id, "source": rcpt_ind.source, "hits": rcpt_ind.hits})
        score = max(score, 0.9)
        reasons.insert(0, {"code": "recipient_in_registry", "text": f"Получатель найден в базе мошенников (источник: {rcpt_ind.source}, совпадений: {rcpt_ind.hits})", "weight": 9.0})
    if call and call.counterparty_hash:
        caller_ind = registry_lookup(db, "phone", call.counterparty_hash)
        if caller_ind:
            hits.append({"what": "caller", "indicator_id": caller_ind.id, "source": caller_ind.source, "hits": caller_ind.hits})
            score = max(score, 0.88)
            reasons.insert(0, {"code": "caller_in_registry", "text": "Номер, с которым говорит клиент, есть в базе мошенников", "weight": 8.0})
    if len(hits) == 2:
        score = max(score, 0.97)

    score = round(score, 3)
    decision = "allow"
    for name in ("challenge", "hold", "block"):
        if score >= THRESHOLDS[name]:
            decision = name
    # "block" means "linked to known fraud" and is shown to the customer as such,
    # so it requires evidence from the registry. A behavioural score alone caps at "hold".
    if decision == "block" and not hits:
        decision = "hold"
    return Assessment(score, decision, reasons, {k: round(v, 3) for k, v in feats.items()}, call_info, hits)
