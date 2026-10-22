"""Regression tests for the first hardening cycle."""
from datetime import datetime, timedelta, timezone

from qorgan.db import SessionLocal
from qorgan.models import Customer, Transfer
from qorgan.routers.ops import _belongs
from qorgan.seed import DEMO_CUSTOMER, luhn_complete

from .conftest import BANK, BOT
from .test_flow import NEW_CARD, score


def unknown_call(client, **kw):
    body = {"customer_id": DEMO_CUSTOMER, "channel": "whatsapp", "in_contacts": False, **kw}
    return client.post("/v1/signals/call", headers=BANK, json=body).json()


def test_idempotent_retry_returns_same_transfer(client):
    body = {"customer_id": DEMO_CUSTOMER, "amount": 5000, "recipient": {"kind": "card", "value": NEW_CARD}}
    h = {**BANK, "Idempotency-Key": "pay-123"}
    a = client.post("/v1/transfers/score", headers=h, json=body).json()
    b = client.post("/v1/transfers/score", headers=h, json=body).json()
    assert a["transfer"]["id"] == b["transfer"]["id"] and b["replayed"]
    assert len(client.get("/v1/transfers", headers=BANK).json()) == 1


def test_denying_dictation_does_not_make_recipient_trusted(client):
    unknown_call(client)
    first = score(client, NEW_CARD, 45000, {"pasted_recipient": True})["transfer"]
    assert first["decision"] == "challenge"
    client.post(f"/v1/transfers/{first['id']}/challenge", headers=BANK, json={"dictated": False})
    second = score(client, NEW_CARD, 45000, {"pasted_recipient": True})["transfer"]
    assert second["features"]["recipient_new"] == 1.0


def test_customer_can_confirm_only_after_cooling_off(client):
    unknown_call(client)
    t = score(client, NEW_CARD, 800000, {"max_pause_ms": 14000, "pasted_recipient": True, "app_switches": 3})["transfer"]
    assert t["decision"] == "hold"
    assert client.post(f"/v1/transfers/{t['id']}/confirm", headers=BANK).status_code == 409
    with SessionLocal() as db:
        db.get(Transfer, t["id"]).hold_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    r = client.post(f"/v1/transfers/{t['id']}/confirm", headers=BANK)
    assert r.status_code == 200 and r.json()["status"] == "released"


def test_mule_fan_in_holds_transfer(client):
    mule = luhn_complete("440043246824682")
    with SessionLocal() as db:
        for i in range(3):
            db.add(Customer(id=f"cus_victim_{i}", name=f"V{i}", age=50))
        db.commit()
    for i in range(3):
        client.post("/v1/transfers/score", headers=BANK, json={"customer_id": f"cus_victim_{i}", "amount": 9000, "recipient": {"kind": "card", "value": mule}})
    t = score(client, mule, 9000)["transfer"]
    assert t["decision"] == "hold"
    assert any(r["code"] == "recipient_fan_in_log" for r in t["reasons"])


def test_screen_sharing_during_unknown_call_holds(client):
    unknown_call(client)
    t = score(client, NEW_CARD, 10000, {"screen_sharing": True})["transfer"]
    assert t["decision"] in ("hold", "block")


def test_kazakh_messages(client):
    unknown_call(client)
    r = client.post("/v1/transfers/score", headers=BANK, json={
        "customer_id": DEMO_CUSTOMER, "amount": 800000, "recipient": {"kind": "card", "value": NEW_CARD},
        "behavior": {"max_pause_ms": 14000, "pasted_recipient": True, "app_switches": 3}, "lang": "kk",
    }).json()
    assert r["customer_message"]["title"].startswith("Аударым")
    assert any("қоңырау" in x["text"] or "сөйлес" in x["text"] for x in r["transfer"]["reasons"])


def test_bank_call_check(client):
    assert client.get(f"/v1/customers/{DEMO_CUSTOMER}/call-check", headers=BANK).json()["bank_is_calling"] is False
    bc = client.post("/v1/bank-calls", headers=BANK, json={"customer_id": DEMO_CUSTOMER, "agent": "Колл-центр"}).json()
    assert client.get(f"/v1/customers/{DEMO_CUSTOMER}/call-check", headers=BANK).json()["bank_is_calling"] is True
    client.post(f"/v1/bank-calls/{bc['id']}/end", headers=BANK)
    assert client.get(f"/v1/customers/{DEMO_CUSTOMER}/call-check", headers=BANK).json()["bank_is_calling"] is False


def test_stream_filter_isolates_customers():
    assert _belongs('{"type":"guardian.alert","payload":{"customer_id":"a"}}', "a")
    assert not _belongs('{"type":"guardian.alert","payload":{"customer_id":"b"}}', "a")
    assert _belongs('{"type":"demo.reset","payload":{}}', "a")


def test_model_card(client):
    card = client.get("/v1/model", headers=BANK).json()
    assert card["metrics_on_synthetic_holdout"]["roc_auc"] > 0.9
    assert "remote_control" in card["weights"]


def test_bot_cannot_score_transfers(client):
    r = client.post("/v1/transfers/score", headers=BOT, json={"customer_id": DEMO_CUSTOMER, "amount": 1, "recipient": {"kind": "card", "value": NEW_CARD}})
    assert r.status_code == 403


def test_device_state_from_sdk_counts(client):
    unknown_call(client)
    client.post("/v1/signals/device", headers=BANK, json={"customer_id": DEMO_CUSTOMER, "remote_access_app": True})
    t = score(client, NEW_CARD, 10000)["transfer"]
    assert t["features"]["remote_control"] == 1.0 and t["decision"] in ("hold", "block")
