"""Qorgan Telegram bot.

- Anyone: forward a suspicious message / link / card / number → verdict.
- Guardians: /link CODE → receive and answer «бабушка переводит деньги» alerts.
- /apa: honeypot mode. Messages in this chat are answered by Apa.AI as a scammer's
  "victim". In production Apa runs on bait numbers via userbot accounts; this mode
  lets anyone play the scammer for demos and red-teaming.
"""
import asyncio
import logging
import os
import random

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

API_URL = os.getenv("QORGAN_API_URL", "http://localhost:8000")
API_KEY = os.getenv("QORGAN_BOT_KEY", "dev-bot-key")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

log = logging.getLogger("qorgan.bot")
dp = Dispatcher()
api = httpx.AsyncClient(base_url=API_URL, headers={"X-API-Key": API_KEY}, timeout=60)
apa_chats: set[int] = set()

VERDICT = {
    "dangerous": "🔴 <b>Опасно.</b> Это похоже на мошенничество.",
    "suspicious": "🟠 <b>Подозрительно.</b> Будьте осторожны.",
    "no_data": "⚪ <b>Данных нет.</b> Это не значит, что безопасно.",
}
ADVICE = (
    "\n\nЧто делать: не переводите деньги, не называйте коды из SMS, не устанавливайте приложения по просьбе "
    "звонящего. Положите трубку и перезвоните в банк по номеру на обороте карты."
)

START = (
    "👋 Я <b>Qorgan</b>, защита от мошенников.\n\n"
    "• Перешлите мне подозрительное сообщение, ссылку, номер карты или телефона, я проверю.\n"
    "• /link КОД: стать доверенным человеком (внук/дочь) и получать предупреждения, если близкого пытаются обмануть.\n"
    "• /apa: режим <b>Апа.AI</b>, поговорите с нашей «бабушкой» от лица мошенника и посмотрите, как она вытягивает реквизиты.\n"
    "• /stop: выйти из режима Апа."
)


@dp.message(CommandStart())
async def start(m: Message) -> None:
    await m.answer(START)


@dp.message(Command("apa"))
async def apa_on(m: Message) -> None:
    apa_chats.add(m.chat.id)
    await m.answer("🧓 Режим Апа.AI включён. Пишите от лица мошенника. /stop чтобы выйти.")


@dp.message(Command("stop"))
async def apa_off(m: Message) -> None:
    apa_chats.discard(m.chat.id)
    await m.answer("Режим Апа.AI выключен. Теперь я снова проверяю сообщения.")


@dp.message(Command("link"))
async def link(m: Message, command: CommandObject) -> None:
    if not command.args:
        await m.answer("Отправьте: /link КОД (код показан в приложении банка вашего близкого).")
        return
    r = await api.post("/v1/guardians/link", json={"code": command.args.strip(), "telegram_chat_id": str(m.chat.id)})
    if r.status_code == 200:
        d = r.json()
        await m.answer(f"✅ Готово, {d['name']}. Теперь вы доверенный человек для <b>{d['customer_name']}</b>. Если её попытаются обмануть, я напишу сюда.")
    else:
        await m.answer("Код не найден. Проверьте и попробуйте ещё раз.")


@dp.message(Command("check"))
async def check_cmd(m: Message, command: CommandObject) -> None:
    await check_text(m, command.args or "")


@dp.callback_query(F.data.startswith("g:"))
async def guardian_answer(cb: CallbackQuery) -> None:
    _, verdict, transfer_id = cb.data.split(":", 2)
    r = await api.post(f"/v1/transfers/{transfer_id}/guardian", json={"approve": verdict == "ok"})
    if r.status_code != 200:
        await cb.answer("Уже обработано", show_alert=True)
        return
    status = r.json()["status"]
    text = {"cancelled": "⛔ Перевод остановлен. Позвоните ей и успокойте.", "released": "✅ Перевод разрешён."}.get(status, "Передано в банк на проверку.")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(text)
    await cb.answer()


async def check_text(m: Message, text: str) -> None:
    if not text.strip():
        await m.answer("Пришлите текст, ссылку, номер карты или телефона.")
        return
    r = await api.post("/v1/reports", json={"text": text, "reporter": f"tg:{m.from_user.id if m.from_user else ''}"})
    d = r.json()
    lines = [VERDICT[d["verdict"]]]
    if d.get("scheme"):
        lines.append(f"Схема: {d['scheme_label']}")
    for c in d["checks"]:
        if c.get("valid"):
            mark = "🔴" if c["verdict"] == "dangerous" else "🟠" if c["verdict"] == "suspicious" else "⚪"
            reason = f": {c['reasons'][0]}" if c["reasons"] else ""
            lines.append(f"{mark} <code>{c['display']}</code>{reason}")
    if d["verdict"] != "no_data":
        lines.append(ADVICE)
    await m.answer("\n".join(lines))


@dp.message(F.text | F.caption)
async def any_text(m: Message, bot: Bot) -> None:
    text = m.text or m.caption or ""
    if m.chat.id in apa_chats:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
        r = await api.post("/v1/apa/message", json={"conversation_id": f"tg:{m.chat.id}", "channel": "telegram", "text": text})
        d = r.json()
        await asyncio.sleep(random.uniform(1.0, 2.5))  # a grandmother types slowly
        await m.answer(d["reply"], parse_mode=None)
        return
    await check_text(m, text)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
