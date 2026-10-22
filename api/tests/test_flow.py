from qorgan.seed import DEMO_CUSTOMER, DEMO_DROP_CARD, DEMO_FAMILY_CARD, luhn_complete

from .conftest import BANK, BOT

NEW_CARD = luhn_complete("440043123412341")


def score(client, card, amount, behavior=None):
    r = client.post("/v1/transfers/score", headers=BANK, json={
        "customer_id": DEMO_CUSTOMER, "amount": amount, "recipient": {"kind": "card", "value": card},
        "behavior": behavior or {}, "local_hour": 14,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_auth_required(client):
    assert client.post("/v1/transfers/score", json={}).status_code == 401
    assert client.post("/v1/apa/message", headers=BANK, json={"conversation_id": "x", "text": "hi"}).status_code == 403


def test_normal_transfer_to_family_is_allowed(client):
    res = score(client, DEMO_FAMILY_CARD, 10000)
    assert res["transfer"]["decision"] == "allow"
    assert res["transfer"]["status"] == "completed"


def test_transfer_during_unknown_call_is_held_and_guardian_alerted(client):
    call = client.post("/v1/signals/call", headers=BANK, json={
        "customer_id": DEMO_CUSTOMER, "channel": "whatsapp", "counterparty": "+77011112233", "in_contacts": False,
    }).json()
    res = score(client, NEW_CARD, 800000, {"max_pause_ms": 14000, "corrections": 4, "session_seconds": 200, "pasted_recipient": True, "app_switches": 3})
    t = res["transfer"]
    assert t["decision"] == "hold", t  # behavioural risk alone never claims "linked to fraud"
    assert t["hold_until"]
    assert res["guardians_notified"] == ["grd_demo_arman"]
    codes = {r["code"] for r in t["reasons"]}
    assert "call_active" in codes or "unknown_caller" in codes
    # Guardian stops it.
    r = client.post(f"/v1/transfers/{t['id']}/guardian", headers=BOT, json={"approve": False})
    assert r.json()["status"] == "cancelled"
    client.post(f"/v1/signals/call/{call['id']}/end", headers=BANK)
    assert client.get("/v1/stats", headers=BANK).json()["prevented_amount"] == 800000


def test_drop_card_from_registry_is_blocked(client):
    res = score(client, DEMO_DROP_CARD, 20000)
    assert res["transfer"]["decision"] == "block"
    assert res["registry_hits"][0]["what"] == "recipient"


def test_apa_extracts_card_which_then_blocks_transfers(client):
    fresh = luhn_complete("440043777788889")
    r = client.post("/v1/apa/message", headers=BOT, json={"conversation_id": "tg-1", "text": "Апа, служба безопасности банка. Срочно переведите деньги на безопасный счёт " + fresh})
    body = r.json()
    assert body["reply"]
    assert any(x["kind"] == "card" for x in body["extracted"])
    assert body["scheme"] == "fake_bank_security"
    res = score(client, fresh, 5000)
    assert res["transfer"]["decision"] == "block"
    g = client.get("/v1/graph", headers=BANK).json()
    assert len(g["nodes"]) >= 2 and g["edges"]


def test_challenge_flow(client):
    client.post("/v1/signals/call", headers=BANK, json={"customer_id": DEMO_CUSTOMER, "channel": "cellular", "in_contacts": False})
    res = score(client, NEW_CARD, 45000, {"max_pause_ms": 6000, "pasted_recipient": True})
    t = res["transfer"]
    assert t["decision"] == "challenge", t
    assert res["customer_message"]["title"].startswith("Минутку")
    r = client.post(f"/v1/transfers/{t['id']}/challenge", headers=BANK, json={"dictated": True})
    assert r.json()["status"] == "cancelled"


def test_report_and_check(client):
    r = client.post("/v1/reports", headers=BOT, json={"text": "Вам положена выплата от государства, перейдите kaspi-bonus-vyplata.top"})
    assert r.json()["verdict"] == "dangerous"
    c = client.get("/v1/check", headers=BOT, params={"value": "kaspl.kz"}).json()
    assert c["verdict"] in ("dangerous", "suspicious")
