import os
import tempfile

os.environ.setdefault("QORGAN_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")
os.environ["QORGAN_OSINT_ONLINE"] = "off"
os.environ["QORGAN_LLM"] = "off"

import pytest
from fastapi.testclient import TestClient

from qorgan.main import app

BANK = {"X-API-Key": "dev-bank-key"}
BOT = {"X-API-Key": "dev-bot-key"}
ADMIN = {"X-API-Key": "dev-admin-key"}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/v1/demo/reset", headers=ADMIN)
        yield c
