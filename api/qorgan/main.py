import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, SessionLocal, engine
from .events import bus
from .risk.model import get_model
from .routers import demo, intel, ops, signals, transfers
from .seed import seed

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.bind(asyncio.get_running_loop())
    Base.metadata.create_all(engine)
    get_model()  # train/load before the first request
    if settings.seed_demo:
        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(
    title="Qorgan Risk API",
    version="1.0.0",
    description="Связываем сигнал звонка, поведение в приложении и разведданные о мошенниках в риск-скор перевода.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
for r in (transfers, signals, intel, ops, demo):
    app.include_router(r.router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"ok": True, "llm": settings.llm_enabled, "model": get_model().version}
