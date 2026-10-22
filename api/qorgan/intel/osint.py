"""Legal, passive OSINT on domains: lexical analysis, RDAP (WHOIS), Certificate Transparency, DNS.

Nothing here touches the suspect's systems beyond what any browser would do.
"""
import asyncio
import socket
from datetime import datetime, timezone
from functools import lru_cache

import httpx

from ..config import settings
from .extract import norm_domain

# Official domains of brands most often imitated in Kazakhstan.
LEGIT: dict[str, str] = {
    "kaspi.kz": "Kaspi", "halykbank.kz": "Halyk", "homebank.kz": "Halyk Homebank",
    "egov.kz": "eGov", "gov.kz": "gov.kz", "jusan.kz": "Jusan", "bcc.kz": "BCC",
    "forte.kz": "ForteBank", "freedombank.kz": "Freedom Bank", "bankrbk.kz": "Bank RBK",
    "eubank.kz": "Eurasian Bank", "kazpost.kz": "Казпочта", "olx.kz": "OLX",
    "kolesa.kz": "Kolesa", "krisha.kz": "Krisha", "beeline.kz": "Beeline",
    "kcell.kz": "Kcell", "tele2.kz": "Tele2", "telegram.org": "Telegram", "whatsapp.com": "WhatsApp",
}
BRAND_TOKENS = {"kaspi", "halyk", "homebank", "egov", "jusan", "forte", "freedom", "kazpost", "olx", "kolesa", "krisha"}
RISKY_TLDS = {"top", "xyz", "icu", "click", "online", "site", "shop", "live", "cc", "su", "info", "pro", "link"}
LURE_WORDS = ("secure", "verify", "login", "bonus", "vyplat", "kompens", "oplata", "pay", "dostavk", "gift", "prize", "cabinet", "kabinet", "support", "sms", "bank")


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def registrable(domain: str) -> str:
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def lexical(domain: str) -> tuple[float, list[str], str | None]:
    """Offline checks. Returns (score, reasons, imitated_brand)."""
    base = registrable(domain)
    if base in LEGIT:
        return 0.0, [f"Официальный домен {LEGIT[base]}"], None

    score, reasons, brand = 0.0, [], None
    label = base.split(".")[0]
    tld = domain.rsplit(".", 1)[-1]

    for legit, name in LEGIT.items():
        legit_label = legit.split(".")[0]
        if legit_label in domain.replace("-", "") and len(legit_label) >= 3:
            score += 0.5
            brand = name
            reasons.append(f"Использует бренд {name}, но не является {legit}")
            break
        d = levenshtein(label, legit_label)
        if 0 < d <= 2 and len(legit_label) >= 4:
            score += 0.55
            brand = name
            reasons.append(f"Похож на {legit} (тайпсквоттинг, отличие в {d} симв.)")
            break
    if brand is None and any(t in domain for t in BRAND_TOKENS):
        score += 0.4
        reasons.append("Содержит название банка/сервиса")
    if "xn--" in domain:
        score += 0.3
        reasons.append("Punycode: возможна подмена букв (кириллица/латиница)")
    if tld in RISKY_TLDS:
        score += 0.15
        reasons.append(f"Доменная зона .{tld} часто используется для фишинга")
    lures = [w for w in LURE_WORDS if w in domain]
    if lures:
        score += 0.15
        reasons.append(f"Слова-приманки в адресе: {', '.join(lures[:3])}")
    if domain.count("-") >= 2 or sum(c.isdigit() for c in label) >= 3:
        score += 0.1
        reasons.append("Много дефисов/цифр в имени")
    return min(score, 1.0), reasons, brand


async def _rdap(client: httpx.AsyncClient, domain: str) -> dict:
    r = await client.get(f"https://rdap.org/domain/{registrable(domain)}", follow_redirects=True)
    if r.status_code != 200:
        return {}
    data = r.json()
    out: dict = {}
    for ev in data.get("events", []):
        if ev.get("eventAction") == "registration":
            out["registered"] = ev.get("eventDate")
    for ent in data.get("entities", []):
        if "registrar" in ent.get("roles", []):
            for item in ent.get("vcardArray", [None, []])[1]:
                if item[0] == "fn":
                    out["registrar"] = item[3]
    return out


async def _crtsh(client: httpx.AsyncClient, domain: str) -> dict:
    r = await client.get("https://crt.sh/", params={"q": registrable(domain), "output": "json"})
    if r.status_code != 200:
        return {}
    certs = r.json()
    names: set[str] = set()
    first = None
    for c in certs[:500]:
        for n in str(c.get("name_value", "")).split("\n"):
            names.add(n.strip().lstrip("*."))
        nb = c.get("not_before")
        if nb and (first is None or nb < first):
            first = nb
    return {"cert_count": len(certs), "first_cert": first, "names": sorted(names)[:50]}


def _resolve(domain: str) -> list[str]:
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(domain, None, proto=socket.IPPROTO_TCP)})
    except OSError:
        return []


def _age_days(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


async def analyze_domain(raw: str, online: bool | None = None) -> dict:
    domain = norm_domain(raw)
    if not domain:
        raise ValueError("not a domain")
    score, reasons, brand = lexical(domain)
    result: dict = {"domain": domain, "imitates": brand, "rdap": {}, "ct": {}, "ips": []}
    online = settings.osint_online if online is None else online

    if online and registrable(domain) not in LEGIT:
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": "Qorgan-OSINT/1.0"}) as client:
            rdap, ct, ips = await asyncio.gather(
                _rdap(client, domain), _crtsh(client, domain), asyncio.to_thread(_resolve, domain),
                return_exceptions=True,
            )
        result["rdap"] = rdap if isinstance(rdap, dict) else {"error": "unavailable"}
        result["ct"] = ct if isinstance(ct, dict) else {"error": "unavailable"}
        result["ips"] = ips if isinstance(ips, list) else []

        age = _age_days(result["rdap"].get("registered")) if isinstance(rdap, dict) else None
        if age is None and isinstance(ct, dict):
            age = _age_days(ct.get("first_cert"))
        result["age_days"] = age
        if age is not None and age < 7:
            score += 0.4
            reasons.append(f"Домен создан {age} дн. назад")
        elif age is not None and age < 30:
            score += 0.25
            reasons.append(f"Домен молодой: {age} дн.")
        siblings = [n for n in result["ct"].get("names", []) if n and n != domain] if isinstance(ct, dict) else []
        if siblings:
            reasons.append(f"Сертификаты покрывают ещё {len(siblings)} имён (возможная сеть сайтов)")
        if not result["ips"]:
            reasons.append("Домен сейчас не резолвится")

    score = round(min(score, 1.0), 2)
    result["score"] = score
    result["verdict"] = "phishing" if score >= 0.6 else "suspicious" if score >= 0.3 else "clean"
    result["reasons"] = reasons
    return result


@lru_cache(maxsize=4096)
def lexical_cached(domain: str) -> tuple[float, tuple[str, ...], str | None]:
    s, r, b = lexical(domain)
    return s, tuple(r), b
