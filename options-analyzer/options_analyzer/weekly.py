"""Weekly (5 trading-session) direction statistics and an out-of-sample-tested model.

"Weeks" are non-overlapping blocks of 5 sessions anchored at the latest bar, so
the outlook always means "from the latest price to 5 sessions later" no matter
which weekday the tool is run on.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .stats import rsi, sma, wilson_interval

HORIZON = 5
MIN_TRAIN = 104  # two years of weekly blocks before the first out-of-sample forecast
MIN_OOS = 100
FEATURES = ("ret_1w", "ret_4w", "ret_12w", "dist_sma50", "dist_sma200", "rsi14", "vol_ratio", "mkt_4w")
FEATURE_LABELS = {
    "ret_1w": "ผลตอบแทน 1 สัปดาห์ล่าสุด",
    "ret_4w": "ผลตอบแทน 4 สัปดาห์",
    "ret_12w": "ผลตอบแทน 12 สัปดาห์",
    "dist_sma50": "ระยะห่างจาก SMA50",
    "dist_sma200": "ระยะห่างจาก SMA200",
    "rsi14": "RSI(14)",
    "vol_ratio": "ความผันผวนสั้น/ยาว",
    "mkt_4w": "ผลตอบแทนตลาด (SPY) 4 สัปดาห์",
}


@dataclass
class ConditionalStat:
    label: str
    condition: str
    n: int
    up_rate: float
    ci: tuple[float, float]
    differs_from_base: bool


@dataclass
class ModelResult:
    prob_up: float
    n_oos: int
    accuracy: float
    naive_accuracy: float
    brier: float
    naive_brier: float
    skill: float  # Brier skill score vs. the naive base-rate forecast
    t_stat: float
    validated: bool
    features_used: list[str]


@dataclass
class WeeklyOutlook:
    n_weeks: int
    base_up_rate: float
    base_ci: tuple[float, float]
    recent_up_rate: float
    recent_n: int
    abs_move_pct: dict[str, float]
    prob_abs_move_gt: dict[float, float]
    avg_up_move: float
    avg_down_move: float
    conditionals: list[ConditionalStat] = field(default_factory=list)
    model: ModelResult | None = None
    model_note: str = ""
    lean: str = "NEUTRAL"
    lean_reason: str = ""
    weekly_returns: pd.Series | None = None


def build_daily_features(close: pd.Series, market_close: pd.Series | None = None) -> pd.DataFrame:
    lc = np.log(close)
    f = pd.DataFrame(index=close.index)
    f["ret_1w"] = lc - lc.shift(5)
    f["ret_4w"] = lc - lc.shift(20)
    f["ret_12w"] = lc - lc.shift(60)
    f["dist_sma50"] = close / sma(close, 50) - 1
    f["dist_sma200"] = close / sma(close, 200) - 1
    f["rsi14"] = (rsi(close, 14) - 50.0) / 50.0
    dr = lc.diff()
    f["vol_ratio"] = np.log(dr.rolling(20).std() / dr.rolling(100).std())
    if market_close is not None and len(market_close) > 30:
        m = np.log(market_close)
        mret = (m - m.shift(20)).reindex(close.index, method="ffill")
        f["mkt_4w"] = mret
    f["fwd"] = lc.shift(-HORIZON) - lc
    return f


def weekly_blocks(daily: pd.DataFrame) -> pd.DataFrame:
    """Rows every 5 sessions, ending at the latest row."""
    idx = np.arange(len(daily) - 1, -1, -HORIZON)[::-1]
    return daily.iloc[idx]


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    """L2-regularised logistic regression by Newton/IRLS. Intercept is not penalised."""
    n, p = X.shape
    Xb = np.column_stack([np.ones(n), X])
    w = np.zeros(p + 1)
    reg = l2 * np.eye(p + 1)
    reg[0, 0] = 0.0
    for _ in range(iters):
        mu = _sigmoid(Xb @ w)
        W = mu * (1 - mu)
        grad = Xb.T @ (mu - y) + reg @ w
        H = Xb.T @ (Xb * W[:, None]) + reg + 1e-9 * np.eye(p + 1)
        step = np.linalg.solve(H, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return w


def _predict(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return _sigmoid(w[0] + X @ w[1:])


def walk_forward(X: np.ndarray, y: np.ndarray, min_train: int = MIN_TRAIN) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Expanding-window one-step-ahead forecasts. Returns (model_probs, naive_probs, actual)."""
    probs, naive, actual = [], [], []
    for t in range(min_train, len(y)):
        Xtr, ytr = X[:t], y[:t]
        mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
        sd[sd == 0] = 1.0
        w = fit_logistic((Xtr - mu) / sd, ytr)
        probs.append(float(_predict(w, ((X[t] - mu) / sd)[None, :])[0]))
        naive.append(float(ytr.mean()))
        actual.append(float(y[t]))
    return np.array(probs), np.array(naive), np.array(actual)


def evaluate_model(blocks: pd.DataFrame, features: list[str]) -> tuple[ModelResult | None, str]:
    labelled = blocks.iloc[:-1].dropna(subset=features + ["fwd"])
    current = blocks.iloc[-1]
    if current[features].isna().any():
        return None, "ข้อมูลล่าสุดไม่พอสำหรับคำนวณตัวแปรของโมเดล"
    if len(labelled) < MIN_TRAIN + MIN_OOS:
        return None, (f"ประวัติราคามีเพียง {len(labelled)} สัปดาห์ (ต้องการ ≥ {MIN_TRAIN + MIN_OOS}) "
                      "จึงทดสอบโมเดลย้อนหลังไม่ได้ — ไม่แสดงความน่าจะเป็นจากโมเดล")
    X = labelled[features].to_numpy(dtype=float)
    y = (labelled["fwd"].to_numpy(dtype=float) > 0).astype(float)
    p, base, act = walk_forward(X, y)
    brier = float(np.mean((p - act) ** 2))
    naive_brier = float(np.mean((base - act) ** 2))
    d = (base - act) ** 2 - (p - act) ** 2
    sd = float(np.std(d, ddof=1))
    t_stat = float(np.mean(d) / (sd / math.sqrt(len(d)))) if sd > 0 else 0.0
    skill = 1.0 - brier / naive_brier if naive_brier > 0 else 0.0
    validated = len(act) >= MIN_OOS and skill > 0 and t_stat > 1.645

    mu, sdv = X.mean(axis=0), X.std(axis=0)
    sdv[sdv == 0] = 1.0
    w = fit_logistic((X - mu) / sdv, y)
    x_now = (current[features].to_numpy(dtype=float) - mu) / sdv
    prob_now = float(_predict(w, x_now[None, :])[0])
    res = ModelResult(
        prob_up=prob_now, n_oos=len(act),
        accuracy=float(np.mean((p > 0.5) == (act == 1))),
        naive_accuracy=float(np.mean((base > 0.5) == (act == 1))),
        brier=brier, naive_brier=naive_brier, skill=skill, t_stat=t_stat,
        validated=validated, features_used=features,
    )
    if validated:
        note = (f"โมเดลผ่านการทดสอบนอกตัวอย่าง {len(act)} สัปดาห์: แม่นกว่าการเดาด้วยค่าเฉลี่ยอย่างมีนัยสำคัญ "
                f"(Brier skill {skill:+.1%}, t = {t_stat:.2f})")
    else:
        note = (f"โมเดลไม่ผ่านการทดสอบนอกตัวอย่าง ({len(act)} สัปดาห์, Brier skill {skill:+.1%}, t = {t_stat:.2f}) "
                "— ไม่ดีกว่าการเดาด้วยค่าเฉลี่ยในอดีตอย่างมีนัยสำคัญ จึงไม่ควรใช้ตัวเลขนี้ตัดสินใจ")
    return res, note


def _conditional(blocks: pd.DataFrame, mask: pd.Series, label: str, condition: str,
                 base: float) -> ConditionalStat | None:
    sub = blocks.loc[mask.fillna(False).astype(bool), "fwd"].dropna()
    n = len(sub)
    if n < 20:
        return None
    k = int((sub > 0).sum())
    ci = wilson_interval(k, n)
    return ConditionalStat(label, condition, n, k / n, ci, not (ci[0] <= base <= ci[1]))


def weekly_outlook(close: pd.Series, market_close: pd.Series | None = None) -> WeeklyOutlook:
    daily = build_daily_features(close, market_close)
    blocks = weekly_blocks(daily)
    labelled = blocks.iloc[:-1].dropna(subset=["fwd"])
    fwd = labelled["fwd"]
    n = len(fwd)
    k = int((fwd > 0).sum())
    base = k / n if n else float("nan")
    recent = fwd.iloc[-104:]
    simple = np.expm1(fwd)
    abs_move = simple.abs()

    out = WeeklyOutlook(
        n_weeks=n,
        base_up_rate=base,
        base_ci=wilson_interval(k, n),
        recent_up_rate=float((recent > 0).mean()) if len(recent) else float("nan"),
        recent_n=len(recent),
        abs_move_pct={
            "median": float(abs_move.median()),
            "p75": float(abs_move.quantile(0.75)),
            "p90": float(abs_move.quantile(0.90)),
        },
        prob_abs_move_gt={x: float((abs_move > x).mean()) for x in (0.02, 0.05, 0.10)},
        avg_up_move=float(simple[simple > 0].mean()) if (simple > 0).any() else float("nan"),
        avg_down_move=float(simple[simple < 0].mean()) if (simple < 0).any() else float("nan"),
        weekly_returns=simple,
    )

    cur = blocks.iloc[-1]
    conds = []
    if pd.notna(cur["dist_sma50"]):
        above = cur["dist_sma50"] > 0
        conds.append(_conditional(labelled, (labelled["dist_sma50"] > 0) == above, "แนวโน้มระยะกลาง",
                                  "ราคาอยู่เหนือ SMA50" if above else "ราคาอยู่ใต้ SMA50", base))
    if pd.notna(cur["dist_sma200"]):
        above = cur["dist_sma200"] > 0
        conds.append(_conditional(labelled, (labelled["dist_sma200"] > 0) == above, "แนวโน้มระยะยาว",
                                  "ราคาอยู่เหนือ SMA200" if above else "ราคาอยู่ใต้ SMA200", base))
    if pd.notna(cur["ret_1w"]):
        up = cur["ret_1w"] > 0
        conds.append(_conditional(labelled, (labelled["ret_1w"] > 0) == up, "สัปดาห์ที่ผ่านมา",
                                  "สัปดาห์ก่อนปิดบวก" if up else "สัปดาห์ก่อนปิดลบ", base))
    if pd.notna(cur["rsi14"]):
        r_now = cur["rsi14"] * 50 + 50
        r_hist = labelled["rsi14"] * 50 + 50
        if r_now >= 70:
            mask, text = r_hist >= 70, "RSI ≥ 70 (overbought)"
        elif r_now <= 30:
            mask, text = r_hist <= 30, "RSI ≤ 30 (oversold)"
        else:
            mask, text = (r_hist > 30) & (r_hist < 70), "RSI อยู่ระหว่าง 30–70"
        conds.append(_conditional(labelled, mask, "โมเมนตัม", text, base))
    out.conditionals = [c for c in conds if c is not None]

    features = [f for f in FEATURES if f in blocks.columns]
    out.model, out.model_note = evaluate_model(blocks, features)
    out.lean, out.lean_reason = decide_lean(out)
    return out


LEAN_LABELS = {
    "CALL": "เอียงไปทาง CALL (มีหลักฐานทางสถิติรองรับ)",
    "LEAN_CALL": "เอียง CALL เล็กน้อย (จากสถิติระยะยาวเท่านั้น)",
    "NEUTRAL": "เป็นกลาง — ไม่มีความได้เปรียบทางสถิติที่ชัดเจน",
    "LEAN_PUT": "เอียง PUT เล็กน้อย (จากสถิติระยะยาวเท่านั้น)",
    "PUT": "เอียงไปทาง PUT (มีหลักฐานทางสถิติรองรับ)",
}


def decide_lean(o: WeeklyOutlook) -> tuple[str, str]:
    m = o.model
    if m is not None and m.validated:
        if m.prob_up >= 0.55:
            return "CALL", f"โมเดลที่ผ่านการทดสอบให้โอกาสขึ้น {m.prob_up:.0%} ใน 5 วันทำการข้างหน้า"
        if m.prob_up <= 0.45:
            return "PUT", f"โมเดลที่ผ่านการทดสอบให้โอกาสขึ้นเพียง {m.prob_up:.0%} ใน 5 วันทำการข้างหน้า"
        return "NEUTRAL", f"โมเดลให้โอกาสขึ้น {m.prob_up:.0%} ซึ่งใกล้ 50% เกินไป"
    lo, hi = o.base_ci
    if lo > 0.5:
        return "LEAN_CALL", (f"ในอดีตสัปดาห์ที่ปิดบวกมี {o.base_up_rate:.0%} (ช่วงเชื่อมั่น 95%: {lo:.0%}–{hi:.0%}) "
                             "ซึ่งสะท้อนแนวโน้มระยะยาวของหุ้น ไม่ใช่สัญญาณจับจังหวะรายสัปดาห์")
    if hi < 0.5:
        return "LEAN_PUT", (f"ในอดีตสัปดาห์ที่ปิดบวกมีเพียง {o.base_up_rate:.0%} (ช่วงเชื่อมั่น 95%: {lo:.0%}–{hi:.0%}) "
                            "ซึ่งสะท้อนแนวโน้มขาลงระยะยาว ไม่ใช่สัญญาณจับจังหวะรายสัปดาห์")
    return "NEUTRAL", (f"สัปดาห์ขึ้น/ลงในอดีตใกล้เคียงกัน ({o.base_up_rate:.0%} ขึ้น, ช่วงเชื่อมั่น {lo:.0%}–{hi:.0%}) "
                       "และไม่มีโมเดลที่ผ่านการทดสอบ")
