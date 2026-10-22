"""Database schema.

Privacy by design: card numbers and phone numbers are never stored in clear.
Matching happens on an HMAC hash (see intel.extract.fingerprint); only a masked
form is kept for display.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cus"))
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int] = mapped_column(Integer, default=40)
    # Median of the customer's usual transfers, KZT. Kept by the bank, sent with the score request.
    typical_amount: Mapped[float] = mapped_column(Float, default=20000)
    # Latest device state reported by the SDK (screen sharing / remote-access app running).
    screen_sharing: Mapped[bool] = mapped_column(Boolean, default=False)
    remote_access_app: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    guardians: Mapped[list["Guardian"]] = relationship(back_populates="customer", cascade="all, delete-orphan")


class Guardian(Base):
    """A trusted person (e.g. a grandchild) who is asked to confirm risky transfers."""

    __tablename__ = "guardians"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("grd"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    relation: Mapped[str] = mapped_column(String(60), default="")
    phone_masked: Mapped[str] = mapped_column(String(32), default="")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    link_code: Mapped[str] = mapped_column(String(12), default=lambda: uuid4().hex[:6].upper())
    min_amount: Mapped[float] = mapped_column(Float, default=50000)

    customer: Mapped[Customer] = relationship(back_populates="guardians")


class KnownRecipient(Base):
    """Recipients the customer has paid before (hash only)."""

    __tablename__ = "known_recipients"
    __table_args__ = (UniqueConstraint("customer_id", "recipient_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    recipient_hash: Mapped[str] = mapped_column(String(64), index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)


class CallSignal(Base):
    """A call event from the bank app on the device or from a telecom operator.

    Only metadata: never audio or transcript.
    """

    __tablename__ = "call_signals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("call"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="device")  # device | telco
    channel: Mapped[str] = mapped_column(String(16), default="cellular")  # cellular | whatsapp | telegram | voip | unknown
    counterparty_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counterparty_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    in_contacts: Mapped[bool] = mapped_column(Boolean, default=False)
    spoof_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    mass_caller: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BankCall(Base):
    """An outbound call the bank's own call centre is making right now.

    Lets the app tell the customer «банк вам сейчас НЕ звонит» during any other call.
    """

    __tablename__ = "bank_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("bcall"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(80), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Indicator(Base):
    """Threat-intel registry entry: drop card, scam phone, phishing domain, IBAN, URL, account."""

    __tablename__ = "indicators"
    __table_args__ = (UniqueConstraint("kind", "value_hash"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ind"))
    kind: Mapped[str] = mapped_column(String(16), index=True)  # card | phone | domain | url | iban | account
    value_hash: Mapped[str] = mapped_column(String(64), index=True)
    display: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(40), default="manual")  # apa | report | osint | bank | manual | demo
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    hits: Mapped[int] = mapped_column(Integer, default=1)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Case(Base):
    """A scam conversation captured by Apa or a user report."""

    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("case"))
    channel: Mapped[str] = mapped_column(String(20), default="telegram")
    external_id: Mapped[str] = mapped_column(String(80), index=True)
    scheme: Mapped[str] = mapped_column(String(60), default="unknown")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["CaseMessage"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseMessage.id"
    )
    links: Mapped[list["CaseIndicator"]] = relationship(cascade="all, delete-orphan")


class CaseMessage(Base):
    __tablename__ = "case_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # scammer | apa
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="messages")


class CaseIndicator(Base):
    __tablename__ = "case_indicators"
    __table_args__ = (UniqueConstraint("case_id", "indicator_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    indicator_id: Mapped[str] = mapped_column(ForeignKey("indicators.id", ondelete="CASCADE"), index=True)


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("trf"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    recipient_kind: Mapped[str] = mapped_column(String(16))
    recipient_hash: Mapped[str] = mapped_column(String(64), index=True)
    recipient_masked: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(16))  # allow | challenge | hold | block
    status: Mapped[str] = mapped_column(String(24))  # completed | pending_challenge | held | cancelled | released
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(60), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Event(Base):
    """Audit log + feed for the console."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
