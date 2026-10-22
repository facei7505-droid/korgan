from typing import Literal

from pydantic import BaseModel, Field

Channel = Literal["cellular", "whatsapp", "telegram", "voip", "unknown"]


class CallStart(BaseModel):
    customer_id: str
    source: Literal["device", "telco"] = "device"
    channel: Channel = "cellular"
    counterparty: str | None = Field(None, description="Caller number; hashed on arrival, never stored raw")
    in_contacts: bool = False
    spoof_suspected: bool = False
    mass_caller: bool = False


class BehaviorIn(BaseModel):
    max_pause_ms: float = 0
    corrections: int = 0
    session_seconds: float = 0
    pasted_recipient: bool = False
    app_switches: int = 0
    screen_sharing: bool = False
    remote_access_app: bool = False


class Recipient(BaseModel):
    kind: Literal["card", "phone", "iban"]
    value: str


class ScoreRequest(BaseModel):
    customer_id: str
    amount: float = Field(gt=0)
    recipient: Recipient
    behavior: BehaviorIn = BehaviorIn()
    local_hour: int | None = Field(None, ge=0, le=23)
    lang: Literal["ru", "kk"] = "ru"


class ChallengeAnswer(BaseModel):
    dictated: bool = Field(description="Customer's answer to «Вам сейчас кто-то диктует, что делать?»")


class GuardianAnswer(BaseModel):
    approve: bool
    guardian_id: str | None = None


class IndicatorIn(BaseModel):
    value: str
    kind: Literal["card", "phone", "iban", "url", "domain", "account"] | None = None
    source: str = "manual"
    confidence: float = Field(0.8, ge=0, le=1)
    note: str | None = None


class ReportIn(BaseModel):
    text: str = Field(max_length=8000)
    reporter: str | None = None


class DomainIn(BaseModel):
    domain: str
    save: bool = False


class ApaMessage(BaseModel):
    conversation_id: str
    channel: str = "telegram"
    text: str = Field(max_length=4000)


class GuardianLink(BaseModel):
    code: str
    telegram_chat_id: str


class GuardianIn(BaseModel):
    name: str
    relation: str = ""
    phone: str | None = None
    min_amount: float = 50000


class CustomerIn(BaseModel):
    name: str
    age: int = 40
    typical_amount: float = 20000


class BankCallIn(BaseModel):
    customer_id: str
    agent: str = ""


class DeviceState(BaseModel):
    customer_id: str
    screen_sharing: bool = False
    remote_access_app: bool = False
