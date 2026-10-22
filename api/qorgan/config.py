"""Runtime configuration, read once from environment variables."""
import os
from dataclasses import dataclass, field


def _keys(raw: str) -> dict[str, str]:
    """Parse "role:key,role:key" into {key: role}."""
    out: dict[str, str] = {}
    for pair in filter(None, (p.strip() for p in raw.split(","))):
        role, _, key = pair.partition(":")
        if key:
            out[key] = role
    return out


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("QORGAN_DATABASE_URL", "sqlite:///./qorgan.db")
    # HMAC pepper for hashing card numbers / phones. Must be secret in production.
    pepper: str = os.getenv("QORGAN_PEPPER", "dev-pepper-change-me")
    api_keys: dict[str, str] = field(
        default_factory=lambda: _keys(
            os.getenv(
                "QORGAN_API_KEYS",
                "admin:dev-admin-key,bank:dev-bank-key,bot:dev-bot-key",
            )
        )
    )
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("QORGAN_CORS_ORIGINS", "*").split(",")
    )
    anthropic_model: str = os.getenv("QORGAN_LLM_MODEL", "claude-opus-5-5")
    llm_enabled: bool = bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("QORGAN_LLM", "on") != "off"
    osint_online: bool = os.getenv("QORGAN_OSINT_ONLINE", "on") != "off"
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    seed_demo: bool = os.getenv("QORGAN_SEED_DEMO", "on") != "off"
    # Cooling-off hold for high-risk transfers, minutes.
    hold_minutes: int = int(os.getenv("QORGAN_HOLD_MINUTES", "30"))


settings = Settings()
