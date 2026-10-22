"""Deterministic extraction and normalisation of scam indicators.

Works with no LLM: regexes + validation (Luhn for cards, mod-97 for IBAN).
The LLM layer in apa.py only adds to what is found here.
"""
import hashlib
import hmac
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..config import settings

CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){15,18}\d(?!\d)")
IBAN_RE = re.compile(r"\bKZ\d{2}[0-9A-Z ]{16,20}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<![\d+])(?:\+?7|8)[\s\-\(]*7\d{2}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
URL_RE = re.compile(r"\bhttps?://[^\s<>\"')]+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b(?:[a-z0-9\-]{1,63}\.)+(?:kz|ru|com|net|org|top|xyz|online|site|info|pro|shop|click|link|app|io|me|cc|su|icu|live)\b", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"(?<![\w@])@([a-zA-Z][a-zA-Z0-9_]{4,31})\b")

# Scheme taxonomy. Keywords are lower-case stems in RU/KZ.
SCHEMES: dict[str, tuple[str, ...]] = {
    "fake_bank_security": ("служба безопасности", "безопасный счет", "безопасный счёт", "подозрительная операция", "оформлен кредит", "заявка на кредит", "сотрудник банка", "қауіпсіздік қызметі"),
    "fake_police": ("полиция", "следователь", "кнб", "прокуратур", "уголовное дело", "мвд"),
    "relative_in_trouble": ("ваш сын", "ваш внук", "ваша дочь", "попал в дтп", "попал в беду", "мама, это я", "апа, это я", "балаң"),
    "sms_code": ("код из смс", "скажите код", "продиктуйте код", "смс-код", "код подтверждения"),
    "investment": ("инвестиц", "доход в день", "крипт", "биржа", "трейдинг", "пассивный доход"),
    "prize_or_payout": ("выигрыш", "приз", "компенсац", "выплата от государства", "соцвыплат", "егов", "egov"),
    "marketplace": ("olx", "предоплат", "доставка", "kaspi магазин", "оплатите доставку", "крыша", "krisha"),
    "drop_recruitment": ("подработк", "сдать карту", "аренда карты", "оформи карту", "заработок без вложений"),
}


@dataclass(frozen=True)
class Entity:
    kind: str  # card | phone | iban | url | domain | account
    value: str  # normalised value
    display: str  # safe-to-show form


def fingerprint(kind: str, value: str) -> str:
    """Keyed hash used for matching without storing raw PAN/phone numbers."""
    return hmac.new(settings.pepper.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def norm_card(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    return digits if 16 <= len(digits) <= 19 and luhn_ok(digits) else None


def norm_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return None
    return "+" + digits if digits[1] == "7" else None


def norm_domain(raw: str) -> str | None:
    raw = raw.strip().lower()
    if "://" in raw:
        raw = urlsplit(raw).hostname or ""
    raw = raw.split("/")[0].split(":")[0].strip(".")
    if raw.startswith("www."):
        raw = raw[4:]
    if not raw or "." not in raw:
        return None
    try:
        return raw.encode("idna").decode("ascii")
    except UnicodeError:
        return raw


def mask_card(pan: str) -> str:
    return f"{pan[:6]}******{pan[-4:]}"


def mask_phone(phone: str) -> str:
    return f"{phone[:5]}***{phone[-4:]}"


def to_entity(kind: str, raw: str) -> Entity | None:
    if kind == "card":
        v = norm_card(raw)
        return Entity("card", v, mask_card(v)) if v else None
    if kind == "phone":
        v = norm_phone(raw)
        return Entity("phone", v, mask_phone(v)) if v else None
    if kind == "iban":
        v = re.sub(r"\s", "", raw).upper()
        return Entity("iban", v, f"{v[:6]}…{v[-4:]}") if len(v) == 20 and iban_ok(v) else None
    if kind == "url":
        v = raw.strip().rstrip(".,;")
        return Entity("url", v, v[:300])
    if kind == "domain":
        v = norm_domain(raw)
        return Entity("domain", v, v) if v else None
    if kind == "account":
        v = raw.lstrip("@").lower()
        return Entity("account", v, "@" + v)
    return None


def detect_kind(raw: str) -> str | None:
    """Guess what a single user-supplied value is."""
    s = raw.strip()
    if re.fullmatch(r"@?[a-zA-Z][a-zA-Z0-9_]{4,31}", s) and s.startswith("@"):
        return "account"
    if IBAN_RE.fullmatch(s.replace(" ", "")):
        return "iban"
    if URL_RE.match(s):
        return "url"
    digits = re.sub(r"\D", "", s)
    if re.fullmatch(r"[\d\s\-+()]+", s):
        if 16 <= len(digits) <= 19:
            return "card"
        if 10 <= len(digits) <= 11:
            return "phone"
    if DOMAIN_RE.fullmatch(s.lower()) or ("." in s and " " not in s):
        return "domain"
    return None


def extract(text: str) -> list[Entity]:
    found: dict[tuple[str, str], Entity] = {}

    def add(e: Entity | None) -> None:
        if e:
            found.setdefault((e.kind, e.value), e)

    for m in IBAN_RE.finditer(text):
        add(to_entity("iban", m.group()))
    for m in CARD_RE.finditer(text):
        add(to_entity("card", m.group()))
    for m in PHONE_RE.finditer(text):
        add(to_entity("phone", m.group()))
    urls = [m.group() for m in URL_RE.finditer(text)]
    for u in urls:
        add(to_entity("url", u))
        add(to_entity("domain", u))
    stripped = URL_RE.sub(" ", text)
    for m in DOMAIN_RE.finditer(stripped):
        add(to_entity("domain", m.group()))
    for m in ACCOUNT_RE.finditer(text):
        add(to_entity("account", m.group(1)))
    return list(found.values())


def classify_scheme(text: str) -> str | None:
    low = text.lower().replace("ё", "е")
    best, best_hits = None, 0
    for scheme, keys in SCHEMES.items():
        hits = sum(1 for k in keys if k.replace("ё", "е") in low)
        if hits > best_hits:
            best, best_hits = scheme, hits
    return best


SCHEME_LABELS = {
    "fake_bank_security": "«Служба безопасности банка»",
    "fake_police": "«Полиция / КНБ»",
    "relative_in_trouble": "«Родственник в беде»",
    "sms_code": "Выманивание SMS-кода",
    "investment": "Фейковые инвестиции",
    "prize_or_payout": "«Выигрыш / выплата»",
    "marketplace": "Мошенничество на маркетплейсе",
    "drop_recruitment": "Вербовка дропов",
    "unknown": "Не определена",
}
