"""Out-of-band notifications to guardians (Telegram Bot API)."""
import logging

import httpx

from .config import settings

log = logging.getLogger("qorgan.notify")


def telegram_guardian_alert(chat_id: str, text: str, transfer_id: str) -> bool:
    if not settings.telegram_bot_token or not chat_id:
        return False
    keyboard = {"inline_keyboard": [[
        {"text": "✅ Это она, разрешить", "callback_data": f"g:ok:{transfer_id}"},
        {"text": "⛔ Остановить", "callback_data": f"g:no:{transfer_id}"},
    ]]}
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "reply_markup": keyboard, "parse_mode": "HTML"},
            timeout=5,
        )
        return r.status_code == 200
    except httpx.HTTPError:
        log.exception("telegram notify failed")
        return False
