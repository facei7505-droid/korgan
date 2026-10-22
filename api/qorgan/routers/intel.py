import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..events import emit
from ..intel import apa
from ..intel.extract import SCHEME_LABELS, Entity, classify_scheme, detect_kind, extract, fingerprint, to_entity
from ..intel.osint import analyze_domain, lexical_cached
from ..intel.registry import upsert
from ..models import Case, CaseIndicator, CaseMessage, Indicator, utcnow
from ..schemas import ApaMessage, DomainIn, IndicatorIn, ReportIn
from ..security import require

router = APIRouter(prefix="/v1", tags=["threat intel"])


def ind_out(i: Indicator) -> dict:
    return {
        "id": i.id, "kind": i.kind, "display": i.display, "source": i.source, "confidence": i.confidence,
        "hits": i.hits, "meta": i.meta, "first_seen": i.first_seen, "last_seen": i.last_seen,
    }


def check_entity(db: Session, kind: str, value: str) -> dict:
    ent = to_entity(kind, value)
    if not ent:
        return {"kind": kind, "valid": False, "verdict": "invalid", "reasons": [f"Некорректный формат ({kind})"]}
    ind = db.scalar(select(Indicator).where(Indicator.kind == ent.kind, Indicator.value_hash == fingerprint(ent.kind, ent.value)))
    out = {"kind": ent.kind, "display": ent.display, "valid": True, "in_registry": bool(ind), "indicator": ind_out(ind) if ind else None, "reasons": []}
    score = 0.95 if ind else 0.0
    if ind:
        out["reasons"].append(f"Найдено в базе мошенников (источник: {ind.source}, совпадений: {ind.hits})")
    if ent.kind in ("domain", "url"):
        dom = to_entity("domain", value)
        if dom:
            dom_ind = None if ind else db.scalar(select(Indicator).where(Indicator.kind == "domain", Indicator.value_hash == fingerprint("domain", dom.value)))
            if dom_ind:
                score = max(score, 0.9)
                out["reasons"].append("Домен найден в базе фишинговых сайтов")
            s, reasons, brand = lexical_cached(dom.value)
            score = max(score, s)
            out["reasons"].extend(reasons)
            out["imitates"] = brand
    out["score"] = round(score, 2)
    out["verdict"] = "dangerous" if score >= 0.6 else "suspicious" if score >= 0.3 else "no_data"
    return out


@router.get("/check", dependencies=[require("bank", "bot")])
def check(value: str = Query(..., max_length=500), kind: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Check a card, phone, IBAN, URL, domain or @account against the registry and heuristics."""
    kind = kind or detect_kind(value)
    if not kind:
        raise HTTPException(422, "cannot detect what this value is")
    return check_entity(db, kind, value)


@router.post("/reports", dependencies=[require("bot", "bank")])
def report(body: ReportIn, db: Session = Depends(get_db)) -> dict:
    """A user forwards a suspicious message. Extract everything, check it, return a verdict."""
    entities = extract(body.text)
    checks = [check_entity(db, e.kind, e.value) for e in entities if e.kind != "url" or not any(x.kind == "domain" for x in entities)]
    scheme = classify_scheme(body.text)
    worst = max([c.get("score", 0) for c in checks] + [0.55 if scheme else 0.0])
    verdict = "dangerous" if worst >= 0.6 else "suspicious" if worst >= 0.3 else "no_data"
    emit(db, "report.received", {"scheme": scheme, "verdict": verdict, "entities": [e.display for e in entities], "reporter": body.reporter})
    db.commit()
    return {"verdict": verdict, "scheme": scheme, "scheme_label": SCHEME_LABELS.get(scheme or "unknown"), "checks": checks}


@router.post("/indicators", dependencies=[require("bank", "bot")])
def add_indicator(body: IndicatorIn, db: Session = Depends(get_db)) -> dict:
    kind = body.kind or detect_kind(body.value)
    ent = to_entity(kind, body.value) if kind else None
    if not ent:
        raise HTTPException(422, "invalid indicator")
    ind, created = upsert(db, ent, body.source, body.confidence, {"note": body.note} if body.note else None)
    db.commit()
    return {"created": created, **ind_out(ind)}


@router.get("/indicators", dependencies=[require("bank")])
def list_indicators(kind: str | None = None, q: str | None = None, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Indicator).order_by(Indicator.last_seen.desc()).limit(min(limit, 1000))
    if kind:
        stmt = stmt.where(Indicator.kind == kind)
    if q:
        stmt = stmt.where(Indicator.display.ilike(f"%{q}%"))
    return [ind_out(i) for i in db.scalars(stmt)]


@router.post("/osint/domain", dependencies=[require("bank", "bot")])
async def osint_domain(body: DomainIn, db: Session = Depends(get_db)) -> dict:
    try:
        res = await analyze_domain(body.domain)
    except ValueError:
        raise HTTPException(422, "not a domain")
    if body.save and res["score"] >= 0.3:
        ent = to_entity("domain", res["domain"])
        ind, _ = upsert(db, ent, "osint", res["score"], {"imitates": res["imitates"], "ips": res["ips"], "age_days": res.get("age_days")})
        for sib in res.get("ct", {}).get("names", [])[:20]:
            sib_ent = to_entity("domain", sib)
            if sib_ent and sib_ent.value != ent.value:
                upsert(db, sib_ent, "osint", res["score"] * 0.8, {"sibling_of": ent.value})
        res["indicator_id"] = ind.id
        db.commit()
    return res


# ---- Apa.AI honeypot --------------------------------------------------------

def _occurs(e: Entity, text: str) -> bool:
    if e.kind in ("card", "phone", "iban"):
        digits = re.sub(r"\D", "", text)
        return re.sub(r"\D", "", e.value)[-10:] in digits
    return e.value.lower() in text.lower()


@router.post("/apa/message", dependencies=[require("bot")])
def apa_message(body: ApaMessage, db: Session = Depends(get_db)) -> dict:
    case = db.scalar(select(Case).where(Case.external_id == body.conversation_id, Case.channel == body.channel))
    if not case:
        case = Case(external_id=body.conversation_id, channel=body.channel)
        db.add(case)
        db.flush()
        emit(db, "case.opened", {"case_id": case.id, "channel": case.channel})
    db.add(CaseMessage(case_id=case.id, role="scammer", text=body.text))
    db.flush()
    history = [{"role": m.role, "text": m.text} for m in case.messages][-30:]

    result = apa.turn(history)
    entities = {(e.kind, e.value): e for e in extract(body.text)}
    for x in result.get("extracted", []):
        e = to_entity(x.get("kind", ""), x.get("value", ""))
        if e and _occurs(e, body.text):  # only trust LLM entities that literally occur in the scammer's text
            entities.setdefault((e.kind, e.value), e)

    scheme = result.get("scheme") if result.get("scheme") not in (None, "unknown") else classify_scheme(" ".join(m["text"] for m in history if m["role"] == "scammer"))
    if scheme:
        case.scheme = scheme
    found = []
    for e in entities.values():
        ind, created = upsert(db, e, "apa", 0.85, {"scheme": case.scheme}, case_id=case.id)
        found.append({"kind": e.kind, "display": e.display, "indicator_id": ind.id, "new": created})

    db.add(CaseMessage(case_id=case.id, role="apa", text=result["reply"]))
    case.updated_at = utcnow()
    emit(db, "apa.turn", {
        "case_id": case.id, "scammer": body.text, "apa": result["reply"], "scheme": case.scheme,
        "scheme_label": SCHEME_LABELS.get(case.scheme), "extracted": found, "engine": result.get("engine"),
        "pressure": result.get("pressure"),
    })
    db.commit()
    return {"case_id": case.id, "reply": result["reply"], "scheme": case.scheme, "extracted": found, "engine": result.get("engine")}


@router.get("/cases", dependencies=[require("bank")])
def list_cases(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Case, func.count(CaseIndicator.id))
        .outerjoin(CaseIndicator, CaseIndicator.case_id == Case.id)
        .group_by(Case.id).order_by(Case.updated_at.desc()).limit(limit)
    ).all()
    return [{"id": c.id, "channel": c.channel, "scheme": c.scheme, "scheme_label": SCHEME_LABELS.get(c.scheme), "indicators": n, "updated_at": c.updated_at} for c, n in rows]


@router.get("/cases/{case_id}", dependencies=[require("bank")])
def get_case(case_id: str, db: Session = Depends(get_db)) -> dict:
    c = db.get(Case, case_id)
    if not c:
        raise HTTPException(404, "case not found")
    inds = db.scalars(select(Indicator).join(CaseIndicator, CaseIndicator.indicator_id == Indicator.id).where(CaseIndicator.case_id == c.id)).all()
    return {
        "id": c.id, "channel": c.channel, "scheme": c.scheme, "scheme_label": SCHEME_LABELS.get(c.scheme),
        "messages": [{"role": m.role, "text": m.text, "at": m.created_at} for m in c.messages],
        "indicators": [ind_out(i) for i in inds],
    }


@router.get("/graph", dependencies=[require("bank")])
def graph(db: Session = Depends(get_db)) -> dict:
    """Cytoscape-ready graph: cases and indicators; indicators shared by cases reveal one group."""
    nodes, edges = [], []
    links = db.scalars(select(CaseIndicator)).all()
    case_ids = {l.case_id for l in links}
    ind_ids = {l.indicator_id for l in links}
    for c in db.scalars(select(Case).where(Case.id.in_(case_ids))):
        nodes.append({"data": {"id": c.id, "label": SCHEME_LABELS.get(c.scheme, c.scheme), "type": "case"}})
    for i in db.scalars(select(Indicator).where(or_(Indicator.id.in_(ind_ids), Indicator.source == "osint"))):
        nodes.append({"data": {"id": i.id, "label": i.display, "type": i.kind, "hits": i.hits}})
        sib = (i.meta or {}).get("sibling_of")
        if sib:
            parent = db.scalar(select(Indicator).where(Indicator.kind == "domain", Indicator.value_hash == fingerprint("domain", sib)))
            if parent:
                edges.append({"data": {"id": f"{parent.id}-{i.id}", "source": parent.id, "target": i.id, "type": "ct"}})
    for l in links:
        edges.append({"data": {"id": f"{l.case_id}-{l.indicator_id}", "source": l.case_id, "target": l.indicator_id}})
    known = {n["data"]["id"] for n in nodes}
    edges = [e for e in edges if e["data"]["source"] in known and e["data"]["target"] in known]
    return {"nodes": nodes, "edges": edges}
