from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

is_postgres = settings.database_url.startswith("postgresql")
_engine_kw: dict = {"pool_pre_ping": True}
if is_postgres:
    _engine_kw.update(pool_size=20, max_overflow=20)
else:
    _engine_kw["connect_args"] = {"check_same_thread": False}
engine = create_engine(settings.database_url, **_engine_kw)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

MIGRATION_LOCK = 72_710_001  # arbitrary advisory-lock key shared by all API workers


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def _startup_lock():
    """Serialise startup work across workers/instances (Postgres advisory lock)."""
    if not is_postgres:
        yield
        return
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK})
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK})
            conn.commit()


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.attributes["configure_logger"] = False
    tables = set(inspect(engine).get_table_names())
    if "customers" in tables and "alembic_version" not in tables:
        # Database created before migrations existed (create_all): adopt it at the first revision.
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")


def prepare_database(seed: Callable[[Session], None] | None = None) -> None:
    """Run migrations (and optional seeding) once, even when several workers start together."""
    with _startup_lock():
        _migrate()
        if seed:
            with SessionLocal() as db:
                seed(db)
