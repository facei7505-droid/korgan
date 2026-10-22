"""Demo data: one protected customer, her guardian, payment history and a few known scam indicators."""
from sqlalchemy.orm import Session

from .db import Base, engine
from .intel.extract import fingerprint, luhn_ok, to_entity
from .intel.registry import upsert
from .models import Customer, Guardian, KnownRecipient

DEMO_CUSTOMER = "cus_demo_bibigul"
DEMO_GUARDIAN = "grd_demo_arman"
DEMO_LINK_CODE = "QORGAN"


def luhn_complete(prefix: str) -> str:
    for d in "0123456789":
        if luhn_ok(prefix + d):
            return prefix + d
    raise AssertionError


# Fictional numbers for the demo. They pass Luhn so the validators accept them.
DEMO_DROP_CARD = luhn_complete("440043990011223")
DEMO_FAMILY_CARD = luhn_complete("440043555566667")
DEMO_SCAM_PHONE = "+77000000666"
DEMO_PHISHING = "kaspi-bonus-vyplata.top"


def seed(db: Session) -> None:
    if db.get(Customer, DEMO_CUSTOMER):
        return
    c = Customer(id=DEMO_CUSTOMER, name="Бибигуль Ахметова", age=72, typical_amount=15000)
    db.add(c)
    db.add(Guardian(id=DEMO_GUARDIAN, customer_id=c.id, name="Арман", relation="внук", phone_masked="+7701***4455", link_code=DEMO_LINK_CODE, min_amount=30000))
    db.add(KnownRecipient(customer_id=c.id, recipient_hash=fingerprint("card", DEMO_FAMILY_CARD), count=12))
    db.flush()
    upsert(db, to_entity("card", DEMO_DROP_CARD), "demo", 0.9, {"scheme": "fake_bank_security", "note": "демо: карта дропа"})
    upsert(db, to_entity("phone", DEMO_SCAM_PHONE), "demo", 0.9, {"scheme": "fake_bank_security", "note": "демо: номер мошенника"})
    upsert(db, to_entity("domain", DEMO_PHISHING), "demo", 0.9, {"imitates": "Kaspi"})
    db.commit()


def reset(db: Session) -> None:
    db.close()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed(db)
