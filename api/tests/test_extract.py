from qorgan.intel.extract import classify_scheme, detect_kind, extract, luhn_ok
from qorgan.intel.osint import lexical
from qorgan.seed import DEMO_DROP_CARD


def test_extracts_card_phone_link_from_scam_text():
    card = " ".join(DEMO_DROP_CARD[i:i + 4] for i in range(0, 16, 4))
    text = f"Здравствуйте, служба безопасности Kaspi. Переведите на безопасный счёт {card}, звоните +7 (700) 000-06-66, ссылка https://kaspi-bonus.top/login"
    kinds = {e.kind: e for e in extract(text)}
    assert kinds["card"].display.startswith("440043")
    assert kinds["phone"].value == "+77000000666"
    assert kinds["domain"].value == "kaspi-bonus.top"
    assert classify_scheme(text) == "fake_bank_security"


def test_rejects_non_luhn_numbers():
    assert not luhn_ok("4400430000000001")
    assert not [e for e in extract("номер заказа 1234 5678 9012 3456") if e.kind == "card"]


def test_detect_kind():
    assert detect_kind("+7 701 123 45 67") == "phone"
    assert detect_kind("kaspi-pay.xyz") == "domain"
    assert detect_kind("@scam_helper") == "account"


def test_typosquat_and_legit():
    assert lexical("kaspi.kz")[0] == 0
    score, reasons, brand = lexical("kaspl.kz")
    assert score >= 0.5 and brand == "Kaspi"
    assert lexical("halyk-secure-login.top")[0] >= 0.6
