"""Writing to the threat-intel registry."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..events import emit
from ..models import CaseIndicator, Indicator, utcnow
from .extract import Entity, fingerprint


def upsert(db: Session, ent: Entity, source: str, confidence: float = 0.7, meta: dict | None = None, case_id: str | None = None) -> tuple[Indicator, bool]:
    h = fingerprint(ent.kind, ent.value)
    ind = db.scalar(select(Indicator).where(Indicator.kind == ent.kind, Indicator.value_hash == h))
    created = ind is None
    if created:
        ind = Indicator(kind=ent.kind, value_hash=h, display=ent.display, source=source, confidence=confidence, meta=meta or {})
        db.add(ind)
        db.flush()
    else:
        ind.hits += 1
        ind.last_seen = utcnow()
        ind.confidence = max(ind.confidence, confidence)
        if meta:
            ind.meta = {**(ind.meta or {}), **meta}
    if case_id and not db.scalar(select(CaseIndicator).where(CaseIndicator.case_id == case_id, CaseIndicator.indicator_id == ind.id)):
        db.add(CaseIndicator(case_id=case_id, indicator_id=ind.id))
    emit(db, "indicator.new" if created else "indicator.seen", {
        "id": ind.id, "kind": ind.kind, "display": ind.display, "source": ind.source, "hits": ind.hits, "case_id": case_id,
    })
    return ind, created
