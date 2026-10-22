"""Explainable fraud model.

A logistic regression over interpretable features. Each feature's contribution
(coefficient x standardised value) becomes a human-readable reason, so a bank
analyst and the customer both see *why* a transfer was paused.

Bootstrapped on a synthetic dataset that encodes published patterns of
authorised push payment (APP) fraud. In a pilot it is retrained on the bank's
labelled transfers via `train(X, y)`.
"""
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

FEATURES: list[str] = [
    "call_active",            # 1 if a call is ongoing during the transfer
    "unknown_caller",         # call (ongoing or recent) with a number not in contacts
    "call_minutes_log",       # log1p of the call duration in minutes
    "recent_call_decay",      # exp(-minutes_since_call_end / 30); 1 when ongoing
    "messenger_call",         # call over WhatsApp/Telegram/VoIP
    "telco_risk",             # operator flags: spoofed number or mass-dialer
    "recipient_new",          # never paid this recipient before
    "amount_ratio_log",       # log of amount / customer's typical amount
    "elderly",                # customer age >= 60
    "hesitation",             # behavioural: long pauses / uncertainty, 0..1
    "pasted_recipient",       # recipient pasted or dictated rather than chosen
    "app_switches",           # switches away from the app during the flow (capped)
    "night",                  # 23:00-06:00 local
]

REASON_TEXT: dict[str, str] = {
    "call_active": "Клиент прямо сейчас разговаривает по телефону",
    "unknown_caller": "Звонок с номера, которого нет в контактах",
    "call_minutes_log": "Долгий разговор перед переводом",
    "recent_call_decay": "Перевод сразу после подозрительного звонка",
    "messenger_call": "Звонок через мессенджер (WhatsApp/Telegram)",
    "telco_risk": "Оператор пометил номер: подмена или массовый обзвон",
    "recipient_new": "Новый получатель, раньше переводов не было",
    "amount_ratio_log": "Сумма намного больше обычной для клиента",
    "elderly": "Клиент из группы риска (60+)",
    "hesitation": "Поведение похоже на диктовку: паузы, неуверенность",
    "pasted_recipient": "Реквизиты вставлены, а не выбраны из истории",
    "app_switches": "Клиент переключался между банком и звонком",
    "night": "Ночное время",
}


@dataclass
class Explained:
    probability: float
    contributions: dict[str, float]


class RiskModel:
    def __init__(self) -> None:
        self.scaler = StandardScaler()
        self.clf = LogisticRegression(C=0.1, max_iter=2000)
        self.version = "bootstrap-synthetic-2"

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        Xs = self.scaler.fit_transform(X)
        self.clf.fit(Xs, y)

    def explain(self, x: dict[str, float]) -> Explained:
        vec = np.array([[float(x.get(f, 0.0)) for f in FEATURES]])
        xs = self.scaler.transform(vec)
        p = float(self.clf.predict_proba(xs)[0, 1])
        contrib = {f: float(c) for f, c in zip(FEATURES, (xs[0] * self.clf.coef_[0]))}
        return Explained(p, contrib)


def synthetic_dataset(n: int = 12000, fraud_rate: float = 0.12, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Generate labelled sessions from documented fraud patterns.

    Fraud (APP scam): victim on a long call with an unknown/spoofed number,
    often over a messenger, pays a new recipient an unusually large amount,
    hesitates, pastes dictated details, switches between apps.
    Legit: mostly no call; when there is one it is usually a known contact.
    """
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < fraud_rate).astype(int)
    rows = []
    for label in y:
        if label:
            # Not every scam shows every signal: each one is present with some probability.
            has_call = rng.random() < 0.85
            active = has_call and rng.random() < 0.6
            unknown = has_call and rng.random() < 0.85
            minutes = rng.gamma(2.0, 6.0) if has_call else 0.0
            decay = (1.0 if active else float(np.exp(-rng.exponential(40) / 30))) if has_call else 0.0
            messenger = has_call and rng.random() < 0.55
            telco = has_call and rng.random() < 0.15
            new_rcpt = rng.random() < 0.85
            ratio = rng.lognormal(1.1, 1.1)
            elderly = rng.random() < 0.45
            hes = float(np.clip(rng.normal(0.45, 0.25), 0, 1))
            pasted = rng.random() < 0.55
            switches = min(rng.poisson(1.5), 6)
            night = rng.random() < 0.1
        else:
            has_call = rng.random() < 0.25
            active = has_call and rng.random() < 0.5
            unknown = has_call and rng.random() < 0.35
            minutes = rng.gamma(1.5, 3.0) if has_call else 0.0
            decay = (1.0 if active else float(np.exp(-rng.exponential(60) / 30))) if has_call else 0.0
            messenger = has_call and rng.random() < 0.45
            telco = has_call and rng.random() < 0.02
            new_rcpt = rng.random() < 0.3
            ratio = rng.lognormal(0.0, 0.8)
            elderly = rng.random() < 0.22
            hes = float(np.clip(rng.normal(0.2, 0.18), 0, 1))
            pasted = rng.random() < 0.2
            switches = min(rng.poisson(0.4), 6)
            night = rng.random() < 0.06
        rows.append([
            float(active), float(unknown), float(np.log1p(minutes)), decay, float(messenger),
            float(telco), float(new_rcpt), float(np.log(max(ratio, 0.05))), float(elderly),
            hes, float(pasted), float(switches), float(night),
        ])
    return np.array(rows), y


_model: RiskModel | None = None


def get_model() -> RiskModel:
    global _model
    if _model is None:
        m = RiskModel()
        X, y = synthetic_dataset()
        m.train(X, y)
        _model = m
    return _model
