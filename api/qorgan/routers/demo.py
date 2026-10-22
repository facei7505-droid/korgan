from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..events import emit
from ..seed import DEMO_CUSTOMER, DEMO_DROP_CARD, DEMO_FAMILY_CARD, DEMO_LINK_CODE, DEMO_PHISHING, DEMO_SCAM_PHONE, reset
from ..security import require

router = APIRouter(prefix="/v1/demo", tags=["demo"])


@router.get("", dependencies=[require("bank")])
def demo_info() -> dict:
    return {
        "customer_id": DEMO_CUSTOMER, "drop_card": DEMO_DROP_CARD, "family_card": DEMO_FAMILY_CARD,
        "scam_phone": DEMO_SCAM_PHONE, "phishing_domain": DEMO_PHISHING, "guardian_link_code": DEMO_LINK_CODE,
    }


@router.post("/reset", dependencies=[require("admin")])
def demo_reset(db: Session = Depends(get_db)) -> dict:
    reset(db)
    emit(db, "demo.reset", {})
    db.commit()
    return {"ok": True}
