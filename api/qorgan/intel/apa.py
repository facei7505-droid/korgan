"""Apa.AI: a honeypot persona that keeps scammers talking and makes them reveal
drop cards, phone numbers and phishing links.

Two engines:
- LLM (Claude) with structured output: reply + extracted entities + scheme.
- Scripted fallback that works offline, so a demo never depends on the network.
Regex extraction (extract.py) always runs on top of either.
"""
import json
import logging
import random
import re

from ..config import settings

log = logging.getLogger("qorgan.apa")

SYSTEM_PROMPT = """Ты играешь роль «Бибигуль-апа», 74 года, пенсионерка из Шымкента. Это защитная ловушка (honeypot): \
тебе пишут телефонные и мессенджер-мошенники. Твоя задача: как можно дольше удерживать мошенника в разговоре и \
добиться, чтобы он САМ назвал реквизиты: номер карты или IBAN «безопасного счёта», номер телефона, ссылку, \
имя и «должность», название приложения, которое просит установить.

Стиль:
- Пиши коротко, 1-3 предложения, как пожилой человек в мессенджере. Иногда без запятых, иногда мелкие опечатки.
- Смешивай русский с казахскими словами: «балам», «айналайын», «ойбай», «қарағым», «рахмет».
- Ты доверчивая, медленная, переспрашиваешь, плохо видишь, ищешь очки, путаешь карты («у меня Kaspi и пенсионная»).
- Всегда изображай готовность сделать то, что просят, но «не получается», и проси повторить реквизиты медленно, \
продиктовать номер карты ещё раз, прислать ссылку заново, написать имя.

Жёсткие правила:
- Никогда не раскрывай, что ты ИИ или ловушка. На проверочные вопросы отвечай растерянно, как бабушка.
- Никогда не сообщай реальные персональные данные. Если просят код из SMS или данные карты, давай \
правдоподобные, но выдуманные цифры, которые «не подходят», и переспрашивай.
- Не угрожай, не оскорбляй, не сообщай мошеннику, что его данные собираются.

Кроме ответа, проанализируй ПОСЛЕДНЕЕ сообщение мошенника (и историю) и верни найденные реквизиты мошенника \
(не свои выдуманные) и тип схемы."""

SCHEME_ENUM = [
    "fake_bank_security", "fake_police", "relative_in_trouble", "sms_code", "investment",
    "prize_or_payout", "marketplace", "drop_recruitment", "unknown",
]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Ответ апашки мошеннику"},
        "scheme": {"type": "string", "enum": SCHEME_ENUM},
        "extracted": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["card", "phone", "iban", "url", "domain", "account"]},
                    "value": {"type": "string"},
                },
                "required": ["kind", "value"],
                "additionalProperties": False,
            },
        },
        "pressure": {"type": "number", "description": "0..1 насколько мошенник давит/торопит"},
        "summary": {"type": "string", "description": "Одной фразой: что хочет мошенник"},
    },
    "required": ["reply", "scheme", "extracted", "pressure", "summary"],
    "additionalProperties": False,
}

_client = None


def _anthropic():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def llm_turn(history: list[dict]) -> dict | None:
    """history: [{"role": "scammer"|"apa", "text": ...}]; last item is the scammer's message."""
    if not settings.llm_enabled:
        return None
    messages = []
    for m in history:
        role = "user" if m["role"] == "scammer" else "assistant"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + m["text"]
        else:
            messages.append({"role": role, "content": m["text"]})
    if messages and messages[0]["role"] != "user":
        messages.insert(0, {"role": "user", "content": "(начало переписки)"})
    # Assistant turns are plain replies; ask for the JSON envelope only for the new turn.
    messages[-1]["content"] += "\n\n[Ответь в формате JSON по схеме.]"
    try:
        resp = _anthropic().beta.messages.create(
            model=settings.anthropic_model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except Exception:  # network, auth, rate limit: degrade to the scripted engine
        log.exception("Claude call failed, falling back to scripted Apa")
        return None
    if resp.stop_reason == "refusal":
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    data["engine"] = "claude"
    return data


# ---- scripted fallback -------------------------------------------------------

OPENERS = [
    "Алло балам? кто это пишет",
    "Ассалаумағалейкум айналайын, вы кто будете?",
]
ASK_CARD = [
    "Ойбай, какую карту балам? У меня Kaspi и пенсионная. Напиши ещё раз номер куда переводить, я медленно перепишу",
    "Подожди, очки найду… Номер карты напиши ещё раз, цифры мелкие, не вижу",
    "Я в тетрадку пишу, повтори номер карты по 4 цифры пожалуйста қарағым",
]
ASK_LINK = [
    "Не открывается балам. Скинь ссылку ещё раз, внук говорил на синие буквы нажимать",
    "Айналайын, там что-то на английском. Ты ссылку заново пришли, я нажму",
]
ASK_NAME = [
    "А как вас зовут балам? Я запишу, вдруг внук спросит. И отдел какой?",
    "Вы из какого банка говорите? Имя скажите полностью, я записываю",
]
SMS = [
    "Пришло сообщение… 4 8 1… ой стерлось. Сейчас ещё одно придёт наверное",
    "Код 7350 вроде. Не подходит? Ойбай, может я не то смотрю. А куда переводить говорили, номер карты повтори",
]
APP = [
    "Не могу найти это приложение балам, в телефоне Play Market не открывается. Ссылку пришлите",
]
GENERIC = [
    "Ойбай, я плохо понимаю, медленнее пожалуйста. Что мне сделать надо?",
    "Хорошо балам, я готова. Только скажи куда и сколько, я на бумажке напишу",
    "Подожди, чайник поставлю… Так, говори, я слушаю",
    "Айналайын, а это точно безопасно? Внук ругается когда я на телефоне что-то нажимаю",
]


def scripted_turn(history: list[dict]) -> dict:
    last = history[-1]["text"].lower() if history else ""
    apa_turns = sum(1 for m in history if m["role"] == "apa")
    rnd = random.Random(len(history) * 7919 + len(last))
    if apa_turns == 0 and len(last) < 25:
        reply = rnd.choice(OPENERS)
    elif re.search(r"код|смс|sms", last):
        reply = rnd.choice(SMS)
    elif re.search(r"anydesk|rustdesk|прилож|скача|установ", last):
        reply = rnd.choice(APP)
    elif re.search(r"http|ссылк|сайт|перейд", last):
        reply = rnd.choice(ASK_LINK)
    elif re.search(r"\d{4}|перевед|переве|счет|счёт|iban|реквизит", last):
        reply = rnd.choice(ASK_CARD)
    elif re.search(r"банк|служб|полиц|сотрудник|отдел|следовател", last) and apa_turns < 4:
        reply = rnd.choice(ASK_NAME)
    elif re.search(r"карт|kaspi|каспи|деньг", last):
        reply = rnd.choice(ASK_CARD)
    else:
        reply = rnd.choice(GENERIC)
    pressure = min(1.0, 0.2 + 0.2 * len(re.findall(r"срочно|быстро|немедленно|сейчас же|иначе|заблокир", last)))
    return {"reply": reply, "scheme": "unknown", "extracted": [], "pressure": pressure, "summary": "", "engine": "scripted"}


def turn(history: list[dict]) -> dict:
    return llm_turn(history) or scripted_turn(history)
