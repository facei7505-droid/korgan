"""Scoring a transfer: features -> model -> hard rules -> decision."""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import BankCall, CallSignal, Customer, Indicator, KnownRecipient, Transfer
from .model import REASON_TEXT, REASON_TEXT_KK, get_model

CALL_WINDOW = timedelta(hours=3)
FAN_IN_WINDOW = timedelta(hours=24)
THRESHOLDS = {"challenge": 0.25, "hold": 0.6, "block": 0.85}


@dataclass
class Behavior:
    max_pause_ms: float = 0
    corrections: int = 0
    session_seconds: float = 0
    pasted_recipient: bool = False
    app_switches: int = 0
    screen_sharing: bool = False
    remote_access_app: bool = False

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
    # Unknown callers first: an ongoing chat with the grandson must not mask a scam call that just ended.
    return max(calls, key=lambda c: (not c.in_contacts, c.ended_at is None, _as_utc(c.started_at)))


def bank_is_calling(db: Session, customer_id: str) -> bool:
    """True if the bank's own call centre has an open outbound call to this customer."""
    return db.scalar(select(BankCall.id).where(BankCall.customer_id == customer_id, BankCall.ended_at.is_(None))) is not None


def recipient_fan_in(db: Session, recipient_hash: str, customer_id: str, now: datetime) -> int:
    """Distinct other customers who sent money to this recipient in the last 24h (mule pattern)."""
    return db.scalar(
        select(func.count(func.distinct(Transfer.customer_id))).where(
            Transfer.recipient_hash == recipient_hash,
            Transfer.customer_id != customer_id,
            Transfer.created_at >= now - FAN_IN_WINDOW,
        )
    ) or 0


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
    lang: str = "ru",
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
            "bank_is_calling": bank_is_calling(db, customer.id),
        }

    known = db.scalar(
        select(KnownRecipient).where(
            KnownRecipient.customer_id == customer.id, KnownRecipient.recipient_hash == recipient_hash
        )
    )
    fan_in = recipient_fan_in(db, recipient_hash, customer.id, now)
    hour = local_hour if local_hour is not None else (now + timedelta(hours=5)).hour  # Asia/Almaty, UTC+5
    feats.update(
        recipient_new=float(known is None),
        amount_ratio_log=math.log(max(amount / max(customer.typical_amount, 1), 0.05)),
        elderly=float(customer.age >= 60),
        hesitation=behavior.hesitation(),
        pasted_recipient=float(behavior.pasted_recipient),
        app_switches=float(min(behavior.app_switches, 6)),
        night=float(hour >= 23 or hour < 6),
        remote_control=float(behavior.screen_sharing or behavior.remote_access_app or customer.screen_sharing or customer.remote_access_app),
        recipient_fan_in_log=math.log1p(fan_in),
    )

    explained = get_model().explain(feats)
    score = explained.probability
    kk = lang == "kk"
    texts = REASON_TEXT_KK if kk else REASON_TEXT
    reasons = [
        {"code": f, "text": texts[f], "weight": round(c, 2)}
        for f, c in sorted(explained.contributions.items(), key=lambda kv: -kv[1])
        if c > 0.25 and feats[f] > 0
    ][:5]
    for r in reasons:
        if r["code"] == "unknown_caller" and feats["call_active"]:
            r["text"] = "Клиент дәл қазір контактілерде жоқ нөмірмен сөйлесіп отыр" if kk else "Клиент прямо сейчас говорит с номером, которого нет в контактах"
        if r["code"] == "recipient_fan_in_log":
            r["text"] += f" ({fan_in})"

    # Hard floors: patterns that are rare in legitimate payments whatever the model says.
    if feats["remote_control"] and feats["unknown_caller"] and call and not call.ended_at:
        score = max(score, THRESHOLDS["hold"])  # same trigger Android uses for in-call protection
    if fan_in >= 3:
        score = max(score, THRESHOLDS["hold"])
    # Paying someone new, more than usual, while an unknown number is on the line: always ask.
    # The question costs an honest customer ten seconds.
    if feats["call_active"] and feats["unknown_caller"] and feats["recipient_new"] and amount > customer.typical_amount:
        score = max(score, THRESHOLDS["challenge"])

    # Hard rules from threat intelligence (Apa, reports, other banks).
    hits: list[dict] = []
    rcpt_ind = registry_lookup(db, recipient_kind, recipient_hash)
    if rcpt_ind:
        hits.append({"what": "recipient", "indicator_id": rcpt_ind.id, "source": rcpt_ind.source, "hits": rcpt_ind.hits})
        score = max(score, 0.9)
        reasons.insert(0, {"code": "recipient_in_registry", "weight": 9.0, "text": (
            f"Алушы алаяқтар базасында бар (дереккөз: {rcpt_ind.source})" if kk
            else f"Получатель найден в базе мошенников (источник: {rcpt_ind.source}, совпадений: {rcpt_ind.hits})")})
    if call and call.counterparty_hash:
        caller_ind = registry_lookup(db, "phone", call.counterparty_hash)
        if caller_ind:
            hits.append({"what": "caller", "indicator_id": caller_ind.id, "source": caller_ind.source, "hits": caller_ind.hits})
            score = max(score, 0.88)
            reasons.insert(0, {"code": "caller_in_registry", "weight": 8.0, "text": (
                "Клиент сөйлесіп отырған нөмір алаяқтар базасында бар" if kk
                else "Номер, с которым говорит клиент, есть в базе мошенников")})
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
