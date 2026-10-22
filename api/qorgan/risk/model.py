"""Explainable fraud model.

A logistic regression over interpretable features. Each feature's contribution
(coefficient x standardised value) becomes a human-readable reason, so a bank
analyst and the customer both see *why* a transfer was paused.

Bootstrapped on a synthetic dataset that encodes published patterns of
authorised push payment (APP) fraud. In a pilot it is retrained on the bank's
labelled transfers via `train(X, y)`.
"""
import math
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
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
    "remote_control",         # screen sharing or a remote-access app (AnyDesk, RustDesk...) active
    "recipient_fan_in_log",   # log1p(distinct customers who paid this recipient for the first time in 24h)
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
    "remote_control": "Включена демонстрация экрана или удалённый доступ (AnyDesk и т.п.)",
    "recipient_fan_in_log": "На эту карту за сутки впервые переводили сразу несколько клиентов (признак дропа)",
}

REASON_TEXT_KK: dict[str, str] = {
    "call_active": "Клиент дәл қазір телефонмен сөйлесіп отыр",
    "unknown_caller": "Контактілерде жоқ нөмірден қоңырау",
    "call_minutes_log": "Аударым алдында ұзақ сөйлесу",
    "recent_call_decay": "Күдікті қоңыраудан кейін бірден аударым",
    "messenger_call": "Мессенджер арқылы қоңырау (WhatsApp/Telegram)",
    "telco_risk": "Оператор нөмірді белгіледі: жалған нөмір немесе жаппай қоңырау",
    "recipient_new": "Жаңа алушы, бұрын аударым болмаған",
    "amount_ratio_log": "Сома клиент үшін әдеттегіден әлдеқайда көп",
    "elderly": "Тәуекел тобындағы клиент (60+)",
    "hesitation": "Біреу айтып отырғандай: үзілістер, сенімсіздік",
    "pasted_recipient": "Деректемелер тарихтан таңдалмай, қойылған",
    "app_switches": "Клиент банк пен қоңырау арасында ауысты",
    "night": "Түнгі уақыт",
    "remote_control": "Экранды көрсету немесе қашықтан қол жеткізу қосулы (AnyDesk т.б.)",
    "recipient_fan_in_log": "Бұл картаға бір тәулікте бірнеше клиент алғаш рет аударды (дроп белгісі)",
}


@dataclass
class Explained:
    probability: float
    contributions: dict[str, float]


class RiskModel:
    def __init__(self) -> None:
        self.scaler = StandardScaler()
        self.clf = LogisticRegression(C=0.1, max_iter=2000)
        self.version = "bootstrap-synthetic-3"
        self.metrics: dict[str, float] = {}

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=0, stratify=y)
        self.clf.fit(self.scaler.fit_transform(X_tr), y_tr)
        self._mean, self._scale = self.scaler.mean_, self.scaler.scale_
        self._coef, self._intercept = self.clf.coef_[0], float(self.clf.intercept_[0])
        p = self.clf.predict_proba(self.scaler.transform(X_te))[:, 1]
        self.metrics = {
            "roc_auc": round(float(roc_auc_score(y_te, p)), 4),
            "pr_auc": round(float(average_precision_score(y_te, p)), 4),
            "n_train": int(len(y_tr)), "n_test": int(len(y_te)), "fraud_rate": round(float(y.mean()), 3),
        }

    def card(self) -> dict:
        """Model card: what it is, what it was trained on, how it weighs each signal."""
        return {
            "version": self.version,
            "type": "logistic regression (explainable)",
            "trained_on": "synthetic sessions encoding published APP-fraud patterns; retrain on bank data in pilot",
            "metrics_on_synthetic_holdout": self.metrics,
            "weights": {f: round(float(c), 3) for f, c in zip(FEATURES, self.clf.coef_[0])},
        }

    def explain(self, x: dict[str, float]) -> Explained:
        # Plain numpy on the hot path: same maths as scaler.transform + predict_proba, without
        # sklearn's per-call input validation (~10x faster for a single row).
        xs = (np.fromiter((x.get(f, 0.0) for f in FEATURES), float, len(FEATURES)) - self._mean) / self._scale
        parts = xs * self._coef
        p = float(1.0 / (1.0 + math.exp(-(parts.sum() + self._intercept))))
        return Explained(p, dict(zip(FEATURES, parts.tolist())))


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
            remote = rng.random() < 0.3
            fan_in = rng.poisson(1.2)
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
            remote = rng.random() < 0.005
            fan_in = rng.poisson(0.05)
        rows.append([
            float(active), float(unknown), float(np.log1p(minutes)), decay, float(messenger),
            float(telco), float(new_rcpt), float(np.log(max(ratio, 0.05))), float(elderly),
            hes, float(pasted), float(switches), float(night), float(remote), float(np.log1p(fan_in)),
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
