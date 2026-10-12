"""Self-contained HTML report (charts use Plotly loaded from its CDN)."""
from __future__ import annotations

import html

import numpy as np

from . import calendar_us as cal
from .analysis import AnalysisResult
from .chain import oi_available
from .contracts import ContractEval
from .fmt import DISCLAIMER, STATUS_TH, earnings_note, money, num, ok, pct, vol_points
from .validation import FAIL, PASS, WARN
from .weekly import FEATURE_LABELS, LEAN_LABELS

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
MUTED = "#898781"
GRID = "rgba(137,135,129,0.22)"
STATUS_CLASS = {PASS: "good", WARN: "warn", FAIL: "bad"}
STATUS_ICON = {PASS: "✓", WARN: "!", FAIL: "✕"}

CSS = """
:root{--bg:#f9f9f7;--surface:#fcfcfb;--text:#0b0b0b;--text2:#52514e;--muted:#898781;--line:#e1e0d9;
--good:#0ca30c;--warn:#b57900;--bad:#d03b3b;--accent:#2a78d6}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0d0d0d;--surface:#1a1a19;--text:#f0efec;
--text2:#c3c2b7;--line:#2c2c2a;--warn:#fab219;--accent:#3987e5}}
:root[data-theme="dark"]{--bg:#0d0d0d;--surface:#1a1a19;--text:#f0efec;--text2:#c3c2b7;--line:#2c2c2a;--warn:#fab219;
--accent:#3987e5}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,"Segoe UI",
"Noto Sans Thai","Leelawadee UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 12px;border-bottom:1px solid var(--line);
padding-bottom:6px}
.sub{color:var(--text2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.stat .k{color:var(--text2);font-size:12px}.stat .v{font-size:20px;font-weight:600}
.stat .n{color:var(--muted);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{color:var(--text2);font-weight:600;background:var(--surface);position:sticky;top:0}
td.l,th.l{text-align:left;white-space:normal}
.scroll{overflow-x:auto}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;
border:1px solid currentColor}
.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.lean{font-size:18px;font-weight:700}
.note{color:var(--text2);font-size:13px}
.err{border-color:var(--bad)}
details summary{cursor:pointer;color:var(--accent)}
.chart{min-height:340px}
"""


def _e(x) -> str:
    return html.escape(str(x))


def _badge(status: str) -> str:
    return f'<span class="badge {STATUS_CLASS[status]}">{STATUS_ICON[status]} {STATUS_TH[status]}</span>'


def _stat(k: str, v: str, n: str = "") -> str:
    return f'<div class="stat"><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div><div class="n">{_e(n)}</div></div>'


def _layout(title: str, xaxis: str, yaxis: str, **extra) -> dict:
    axis = dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont=dict(color=MUTED),
                title_font=dict(color=MUTED))
    lay = dict(title=dict(text=title, font=dict(size=14, color=MUTED)), paper_bgcolor="rgba(0,0,0,0)",
               plot_bgcolor="rgba(0,0,0,0)", font=dict(family="system-ui, sans-serif", color=MUTED),
               margin=dict(l=50, r=20, t=40, b=40), legend=dict(orientation="h", y=-0.18),
               xaxis=dict(title=xaxis, **axis), yaxis=dict(title=yaxis, **axis), hovermode="x unified")
    lay.update(extra)
    return lay


def _charts(res: AnalysisResult) -> list[str]:
    try:
        import plotly.graph_objects as go
    except ImportError:
        return ['<p class="note">ติดตั้ง plotly (pip install plotly) เพื่อดูกราฟ</p>']
    figs = []
    hist = res.history
    if hist is not None and len(hist):
        c = hist["Close"]
        last = c.iloc[-260:]
        fig = go.Figure()
        fig.add_scatter(x=last.index, y=last.values, name="ราคาปิด", line=dict(color=BLUE, width=2))
        for n, color in ((50, ORANGE), (200, AQUA)):
            fig.add_scatter(x=last.index, y=c.rolling(n).mean().iloc[-260:].values, name=f"SMA{n}",
                            line=dict(color=color, width=2))
        e = res.selected
        if e is not None and ok(e.expected_move_iv):
            for lvl, label in ((e.spot + e.expected_move_iv, "+1 SD"), (e.spot - e.expected_move_iv, "−1 SD")):
                fig.add_hline(y=lvl, line=dict(color=MUTED, width=1, dash="dot"),
                              annotation_text=f"{label} ถึง {e.expiry}: {lvl:,.2f}",
                              annotation_font_color=MUTED)
        fig.update_layout(**_layout("ราคา 1 ปีล่าสุด (ปรับปันผล/แตกพาร์) และกรอบคาดการณ์ ±1 SD", "", "ราคา"))
        figs.append(fig)

    w = res.weekly
    if w is not None and w.weekly_returns is not None and len(w.weekly_returns):
        r = w.weekly_returns * 100
        fig = go.Figure()
        fig.add_histogram(x=r, nbinsx=60, name="ผลตอบแทน 5 วันทำการ", marker=dict(color=BLUE, line=dict(
            color="rgba(0,0,0,0)", width=2)), hovertemplate="%{x:.1f}%: %{y} สัปดาห์<extra></extra>")
        e = res.selected
        if e is not None and e.straddle_price is not None:
            m = e.straddle_price / e.spot * 100
            for x in (m, -m):
                fig.add_vline(x=x, line=dict(color=MUTED, width=1, dash="dash"),
                              annotation_text=f"straddle {x:+.1f}%", annotation_font_color=MUTED)
        fig.update_layout(**_layout(f"การกระจายผลตอบแทนราย 5 วันทำการ ({w.n_weeks} ช่วง)", "ผลตอบแทน (%)",
                                    "จำนวนสัปดาห์", hovermode="closest", bargap=0.05, showlegend=False))
        figs.append(fig)

    ch = res.chain
    if ch is not None and len(ch) and res.selected is not None:
        u = ch[ch["usable"]]
        spot = res.selected.spot
        fig = go.Figure()
        # Out-of-the-money side only: deep in-the-money quotes have tiny vega, so cent rounding distorts their IV.
        for kind, color, name in (("call", BLUE, "Call"), ("put", ORANGE, "Put")):
            s = u[(u["kind"] == kind) & ((u["strike"] >= spot * 0.98) if kind == "call" else (u["strike"] <= spot * 1.02))]
            fig.add_scatter(x=s["strike"], y=s["iv"] * 100, mode="lines+markers", name=name,
                            line=dict(color=color, width=2), marker=dict(size=8, color=color))
        _min_iv_window(fig, list(u.loc[u["strike"].between(spot * 0.8, spot * 1.2), "iv"] * 100))
        fig.add_vline(x=res.selected.spot, line=dict(color=MUTED, width=1, dash="dot"),
                      annotation_text=f"ราคาหุ้น {res.selected.spot:,.2f}", annotation_font_color=MUTED)
        fig.update_layout(**_layout(f"IV ตาม strike ฝั่ง OTM (หมดอายุ {res.selected.expiry}) — คำนวณเองจากราคากลาง",
                                    "Strike", "IV (%)", hovermode="closest"))
        figs.append(fig)

    if len(res.term) >= 2:
        fig = go.Figure()
        ys = [iv * 100 for _, _, iv in res.term]
        fig.add_scatter(x=[f"{d:%Y-%m-%d}" for d, _, _ in res.term], y=ys,
                        mode="lines+markers", name="ATM IV", line=dict(color=BLUE, width=2), marker=dict(size=8))
        fig.update_layout(**_layout("โครงสร้าง ATM IV ตามวันหมดอายุ", "วันหมดอายุ", "IV (%)", showlegend=False))
        _min_iv_window(fig, ys)
        figs.append(fig)

    if res.focus is not None:
        figs.append(_payoff(go, res.focus, res.selected.spot))

    out = []
    for i, fig in enumerate(figs):
        out.append('<div class="card chart">' + fig.to_html(full_html=False, include_plotlyjs="cdn" if i == 0 else False,
                                                           config={"displaylogo": False, "responsive": True}) + "</div>")
    return out


def _min_iv_window(fig, ys: list[float], points: float = 10.0) -> None:
    """Keep at least a 10-vol-point y window so tiny IV differences do not look dramatic."""
    ys = [y for y in ys if ok(y)]
    if ys and max(ys) - min(ys) < points:
        mid = (max(ys) + min(ys)) / 2
        fig.update_yaxes(range=[max(0.0, mid - points / 2), mid + points / 2])


def _payoff(go, ev: ContractEval, spot: float):
    lo, hi = spot * 0.8, spot * 1.2
    xs = np.linspace(min(lo, ev.breakeven * 0.95), max(hi, ev.breakeven * 1.05), 200)
    intrinsic = np.maximum(xs - ev.strike, 0) if ev.kind == "call" else np.maximum(ev.strike - xs, 0)
    pnl = (intrinsic - ev.price) * 100
    fig = go.Figure()
    fig.add_scatter(x=xs, y=pnl, name="กำไร/ขาดทุน ณ วันหมดอายุ", line=dict(color=BLUE, width=2),
                    hovertemplate="ราคาหุ้น %{x:,.2f}<br>P/L %{y:$,.0f}<extra></extra>")
    fig.add_hline(y=0, line=dict(color=MUTED, width=1))
    fig.add_vline(x=spot, line=dict(color=MUTED, width=1, dash="dot"), annotation_text="ราคาปัจจุบัน",
                  annotation_font_color=MUTED)
    fig.add_vline(x=ev.breakeven, line=dict(color=MUTED, width=1, dash="dash"),
                  annotation_text=f"จุดคุ้มทุน {ev.breakeven:,.2f}", annotation_font_color=MUTED,
                  annotation_position="bottom right")
    fig.update_layout(**_layout(f"กำไร/ขาดทุนต่อสัญญา ณ วันหมดอายุ: {ev.kind.upper()} {ev.strike:g}",
                                "ราคาหุ้น ณ วันหมดอายุ", "USD ต่อสัญญา", showlegend=False))
    return fig


def _validation_html(res: AnalysisResult) -> str:
    v = res.validation
    rows = "".join(f'<tr><td class="l">{_badge(c.status)}</td><td class="l">{_e(c.area)}</td>'
                   f'<td class="l">{_e(c.name)}</td><td class="l">{_e(c.detail)}</td></tr>' for c in v.checks)
    open_attr = " open" if v.count(FAIL) or v.count(WARN) else ""
    errs = "".join(f'<div class="card err"><b class="bad">✕ {_e(e)}</b></div>' for e in res.errors)
    notes = "".join(f'<p class="note">หมายเหตุ: {_e(n)}</p>' for n in res.notes)
    return (f"<h2>1. การตรวจสอบข้อมูล</h2>{errs}"
            f'<div class="grid">{_stat("ผ่าน", str(v.count(PASS)))}{_stat("เตือน", str(v.count(WARN)))}'
            f'{_stat("ไม่ผ่าน", str(v.count(FAIL)))}</div>'
            f'<details{open_attr}><summary>ดูรายการตรวจสอบทั้งหมด</summary><div class="scroll"><table><tr>'
            f'<th class="l">ผล</th><th class="l">หมวด</th><th class="l">รายการ</th><th class="l">รายละเอียด</th></tr>'
            f"{rows}</table></div></details>{notes}")


def _stock_html(res: AnalysisResult) -> str:
    s = res.stock
    t = f"ณ {s.spot_time:%Y-%m-%d %H:%M} ET" if s.spot_time else f"ราคาปิด {s.last_date}"
    cards = [
        _stat("ราคา", num(s.spot), t),
        _stat("เปลี่ยนแปลง 1 วัน / 5 วัน", f"{pct(s.change_1d, 1, True)} / {pct(s.change_5d, 1, True)}",
              f"1 เดือน {pct(s.change_21d, 1, True)}"),
        _stat("กรอบ 52 สัปดาห์", f"{num(s.low_52w)}–{num(s.high_52w)}", f"Max DD 1 ปี {pct(s.max_drawdown_1y)}"),
        _stat("SMA50 / SMA200", f"{num(s.sma50)} / {num(s.sma200)}",
              f"ราคา{'เหนือ' if s.spot > s.sma50 else 'ใต้'} SMA50, {'เหนือ' if s.spot > s.sma200 else 'ใต้'} SMA200"
              if ok(s.sma200) else ""),
        _stat("RSI(14)", num(s.rsi14, 1), ">70 overbought, <30 oversold"),
        _stat("HV20 / HV60 / HV1y", f"{pct(s.hv20, 0)} / {pct(s.hv60, 0)} / {pct(s.hv252, 0)}",
              f"HV20 percentile 1 ปี: {num(s.hv20_percentile, 0)}"),
        _stat("ATR(14)", pct(s.atr14_pct), "ช่วงแกว่งเฉลี่ยต่อวัน"),
        _stat("Beta (1 ปี vs SPY)", num(s.beta_1y), ""),
    ]
    if res.vix is not None:
        cards.append(_stat("VIX", num(res.vix, 1), "ตลาดกลัวสูง" if res.vix >= 30 else ""))
    return f'<h2>2. ภาพรวมหุ้น</h2><div class="grid">{"".join(cards)}</div>'


def _weekly_html(res: AnalysisResult) -> str:
    w = res.weekly
    if w is None:
        return ""
    cls = "good" if w.lean in ("CALL", "LEAN_CALL") else "bad" if w.lean in ("PUT", "LEAN_PUT") else ""
    rows = "".join(
        f'<tr><td class="l">{_e(c.label)}</td><td class="l">{_e(c.condition)}</td><td>{pct(c.up_rate)}</td>'
        f"<td>{c.n}</td><td>{pct(c.ci[0], 0)}–{pct(c.ci[1], 0)}</td>"
        f'<td class="l">{"ต่างจากค่าเฉลี่ยอย่างมีนัยสำคัญ" if c.differs_from_base else "ไม่ต่างอย่างมีนัยสำคัญ"}</td></tr>'
        for c in w.conditionals)
    m = w.model
    model = ""
    if m is not None:
        badge = _badge(PASS if m.validated else FAIL).replace("ไม่ผ่าน", "ไม่ผ่านการทดสอบ").replace(
            "✓ ผ่าน", "✓ ผ่านการทดสอบ")
        model = (f'<div class="card"><b>โมเดลสถิติ (logistic regression + walk-forward)</b> {badge}<br>'
                 f"P(ขึ้นใน 5 วันทำการ) = <b>{pct(m.prob_up)}</b> | ความแม่นยำนอกตัวอย่าง {pct(m.accuracy)} "
                 f"(เดาด้วยค่าเฉลี่ย {pct(m.naive_accuracy)}) | {m.n_oos} สัปดาห์ทดสอบ"
                 f'<p class="note">{_e(w.model_note)}<br>ตัวแปร: '
                 f'{_e(", ".join(FEATURE_LABELS.get(f, f) for f in m.features_used))}</p></div>')
    elif w.model_note:
        model = f'<p class="note">โมเดลสถิติ: {_e(w.model_note)}</p>'
    implied = ""
    if res.selected is not None and ok(res.selected.implied_prob_up):
        implied = _stat("ตลาดออปชั่นประเมิน P(ขึ้น)", pct(res.selected.implied_prob_up),
                        f"risk-neutral ณ {res.selected.expiry}")
    return (
        "<h2>3. ความน่าจะเป็นรายสัปดาห์ (จากราคาล่าสุดไปอีก 5 วันทำการ)</h2>"
        f'<div class="card"><div class="lean {cls}">{_e(LEAN_LABELS[w.lean])}</div>'
        f'<p class="note">{_e(w.lean_reason)}</p></div>'
        f'<div class="grid">{_stat("สัปดาห์ที่ปิดบวกในอดีต", pct(w.base_up_rate), f"{w.n_weeks} สัปดาห์, CI {pct(w.base_ci[0], 0)}–{pct(w.base_ci[1], 0)}")}'
        f'{_stat("2 ปีล่าสุด", pct(w.recent_up_rate), f"{w.recent_n} สัปดาห์")}'
        f'{_stat("การเคลื่อนไหวมัธยฐาน", "±" + pct(w.abs_move_pct["median"]), "90% ของสัปดาห์ไม่เกิน ±" + pct(w.abs_move_pct["p90"]))}'
        f'{_stat("สัปดาห์ขึ้น / ลง เฉลี่ย", f"{pct(w.avg_up_move, 1, True)} / {pct(w.avg_down_move, 1, True)}")}'
        f"{implied}</div>"
        + (f'<div class="card scroll"><b>สถานการณ์คล้ายปัจจุบันในอดีต → สัปดาห์ถัดไปปิดบวก</b><table><tr>'
           f'<th class="l">ปัจจัย</th><th class="l">สถานะปัจจุบัน</th><th>ปิดบวก</th><th>n</th><th>CI 95%</th>'
           f'<th class="l">เทียบค่าเฉลี่ย</th></tr>{rows}</table></div>' if rows else "")
        + model)


def _options_html(res: AnalysisResult) -> str:
    e = res.selected
    if e is None:
        return ""
    s = res.stock
    cards = [
        _stat("ATM IV", pct(e.atm_iv), f"IV ÷ HV20 = {num(e.atm_iv / s.hv20) if ok(s.hv20) and s.hv20 else 'n/a'}"),
        _stat("กรอบ ±1 SD (IV)", f"±{num(e.expected_move_iv)}" if ok(e.expected_move_iv) else "n/a",
              f"±{pct(e.expected_move_iv / e.spot)} → {num(e.spot - e.expected_move_iv)}–{num(e.spot + e.expected_move_iv)}"
              if ok(e.expected_move_iv) else ""),
    ]
    if e.straddle_price is not None:
        cards.append(_stat("Straddle ATM", num(e.straddle_price), f"strike {num(e.straddle_strike)}, "
                           f"±{pct(e.straddle_price / e.spot)}"))
        cards.append(_stat("อดีตเคลื่อนไหวเกิน straddle", pct(e.hist_prob_exceed_straddle),
                           f"{e.sessions} วันทำการ, 5 ปีล่าสุด"))
    cards += [_stat("Put/Call OI", num(e.put_call_oi), f"Volume {num(e.put_call_volume)}"),
              _stat("Skew 25Δ (Put−Call)", vol_points(e.skew_25d), "")]
    earn = res.earnings
    if earn is not None:
        val = "ไม่มี (ETF)" if earn.status == "none" else (str(earn.upcoming[0]) if earn.upcoming else "ยืนยันไม่ได้")
        moves = earnings_note(earn.confirmed) + ". " if earn.upcoming else ""
        if res.earnings_moves:
            avg = sum(abs(m) for _, m in res.earnings_moves) / len(res.earnings_moves)
            moves += f"หลังงบ {len(res.earnings_moves)} ครั้งล่าสุด เคลื่อนไหวเฉลี่ย ±{pct(avg)}"
        cards.append(_stat("ประกาศงบครั้งถัดไป", val, moves))
    closed = ""
    if res.valuation_time is not None and res.valuation_time != res.generated_at:
        closed = (f'<p class="note">ตลาดปิดอยู่: ราคาหุ้นและออปชั่นเป็นราคา ณ ปิดตลาด '
                  f"{res.valuation_time:%Y-%m-%d %H:%M} ET และคำนวณเวลาถึงวันหมดอายุจากจุดนั้น</p>")
    return (f"<h2>4. ออปชั่นหมดอายุ {e.expiry} ({e.dte} วัน / เหลือ {e.sessions} วันทำการ)</h2>{closed}"
            f'<div class="grid">{"".join(cards)}</div>')


def _cands_html(res: AnalysisResult) -> str:
    if not res.candidates:
        return ""
    rows = []
    has_oi = res.chain is not None and oi_available(res.chain)
    for ev in res.candidates:
        n_fail = sum(c.status == FAIL for c in ev.criteria)
        lvl_cls = "good" if ev.risk_level == "ต่ำ" else "warn" if ev.risk_level == "ปานกลาง" else "bad"
        rows.append(
            f'<tr><td class="l">{ev.kind.upper()}</td><td>{ev.strike:g}</td><td>{num(ev.price)}</td>'
            f"<td>{pct(ev.spread_pct)}</td><td>{pct(ev.iv)}</td><td>{ev.delta:+.2f}</td>"
            f"<td>{num(ev.breakeven)} ({pct(ev.breakeven_move, 1, True)})</td><td>{pct(ev.prob_profit)}</td>"
            f"<td>{pct(ev.prob_profit_hist.prob)}</td><td>{pct(1 - ev.prob_itm)}</td><td>{pct(ev.theta_pct)}</td>"
            f"<td>{f'{ev.oi:,.0f}' if has_oi else 'n/a'}</td><td class=\"{lvl_cls}\"><b>{_e(ev.risk_level)}</b> ({ev.risk_score:.0f}, "
            f"ไม่ผ่าน {n_fail})</td></tr>")
    return ('<h2>5. สัญญาใกล้ ATM (ประเมินสำหรับฝั่งผู้ซื้อ)</h2><div class="card scroll"><table><tr>'
            '<th class="l">ประเภท</th><th>Strike</th><th>ราคา</th><th>Spread</th><th>IV</th><th>Delta</th>'
            "<th>จุดคุ้มทุน</th><th>โอกาสกำไร (IV)</th><th>โอกาสกำไร (อดีต)</th><th>เสียหมด</th><th>Theta/วัน</th>"
            f"<th>OI</th><th>ความเสี่ยง</th></tr>{''.join(rows)}</table>"
            '<p class="note">โอกาสกำไร = โอกาสที่ราคาหุ้น ณ วันหมดอายุเกินจุดคุ้มทุน | เสียหมด = โอกาสหมดอายุไร้ค่า | '
            "ดูรายละเอียดเกณฑ์ของแต่ละสัญญาด้วยคำสั่ง --call/--put</p></div>")


def _focus_html(res: AnalysisResult) -> str:
    ev = res.focus
    if ev is None:
        return ""
    hp = ev.prob_profit_hist
    crit = "".join(f'<tr><td class="l">{_badge(c.status)}</td><td class="l">{_e(c.name)}</td>'
                   f'<td class="l">{_e(c.value)}</td><td class="l note">{_e(c.rule)}</td></tr>' for c in ev.criteria)
    lvl_cls = "good" if ev.risk_level == "ต่ำ" else "warn" if ev.risk_level == "ปานกลาง" else "bad"
    cards = [
        _stat("ต้นทุน = ขาดทุนสูงสุด", money(ev.cost), f"ราคา {num(ev.price)} × 100 "
              f"({'ราคากลาง' if ev.price_source == 'mid' else 'ราคาล่าสุด'})"),
        _stat("จุดคุ้มทุน", num(ev.breakeven), f"หุ้นต้องเคลื่อนที่ {pct(ev.breakeven_move, 2, True)}"),
        _stat("โอกาสกำไร (IV)", pct(ev.prob_profit), "ณ วันหมดอายุ"),
        _stat("โอกาสกำไร (อดีต 5 ปี)", pct(hp.prob), f"CI {pct(hp.ci_low, 0)}–{pct(hp.ci_high, 0)}"),
        _stat("กำไร ≥ 100%", pct(ev.prob_double), ""),
        _stat("หมดอายุไร้ค่า", pct(1 - ev.prob_itm), "เสียเงินทั้งหมด"),
        _stat("Delta / Gamma", f"{ev.delta:+.3f} / {ev.gamma:.4f}", f"IV {pct(ev.iv)}"),
        _stat("Theta ต่อวัน", money(ev.theta * 100), f"{pct(ev.theta_pct)} ของราคา"),
    ]
    return (f"<h2>6. สัญญาที่คุณเลือก: {ev.kind.upper()} {ev.strike:g} หมดอายุ {ev.expiry}</h2>"
            f'<div class="card"><span class="lean {lvl_cls}">ระดับความเสี่ยง: {_e(ev.risk_level)}</span> '
            f'(คะแนน {ev.risk_score:.0f}/100 ยิ่งสูงยิ่งเสี่ยง)<p class="note">ระดับนี้ใช้เปรียบเทียบระหว่างสัญญา '
            "การซื้อออปชั่นมีโอกาสเสียเงินทั้งหมดเสมอ</p></div>"
            f'<div class="grid">{"".join(cards)}</div>'
            f'<div class="card scroll"><table><tr><th class="l">ผล</th><th class="l">เกณฑ์</th><th class="l">ค่าจริง</th>'
            f'<th class="l">หลักการ</th></tr>{crit}</table></div>')


def render(res: AnalysisResult) -> str:
    name = res.stock.name if res.stock else res.ticker
    parts = [
        f"<h1>{_e(res.ticker)} — {_e(name)}</h1>",
        f'<div class="sub">รายงานวิเคราะห์ก่อนซื้อออปชั่น | สร้างเมื่อ {_e(cal.stamp(res.generated_at))} '
        f"| ข้อมูล Yahoo Finance | อัตราดอกเบี้ย {pct(res.r, 2)} ({_e(res.r_source)}) | "
        f"ปันผล {pct(res.q, 2)}</div>",
        _validation_html(res),
    ]
    if res.stock is not None:
        parts += [_stock_html(res), _weekly_html(res), _options_html(res), _cands_html(res), _focus_html(res),
                  "<h2>กราฟ</h2>", *_charts(res)]
    parts.append(f'<h2>ข้อควรทราบ</h2><p class="note">{_e(DISCLAIMER)}</p>')
    return ('<!doctype html><html lang="th"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{_e(res.ticker)} Options Risk</title><style>{CSS}</style></head><body><main>"
            + "".join(parts) + "</main></body></html>")


def render_scan(rows: list[AnalysisResult]) -> str:
    body = []
    for res in rows:
        if res.stock is None or res.weekly is None:
            body.append(f'<tr><td class="l">{_e(res.ticker)}</td><td class="l bad" colspan="8">'
                        f'ข้อมูลไม่ผ่านการตรวจสอบ: {_e("; ".join(res.errors))}</td></tr>')
            continue
        w, s, e, m = res.weekly, res.stock, res.selected, res.weekly.model
        cls = "good" if w.lean in ("CALL", "LEAN_CALL") else "bad" if w.lean in ("PUT", "LEAN_PUT") else ""
        body.append(
            f'<tr><td class="l"><b>{_e(res.ticker)}</b></td><td>{num(s.spot)}</td><td>{pct(w.base_up_rate)}</td>'
            f"<td>{pct(m.prob_up) if m else 'n/a'}</td><td>{'ใช่' if m and m.validated else 'ไม่'}</td>"
            f"<td>{pct(e.implied_prob_up) if e else 'n/a'}</td>"
            f"<td>{('±' + pct(e.expected_move_iv / e.spot)) if e and ok(e.expected_move_iv) else 'n/a'}</td>"
            f"<td>{num(e.atm_iv / s.hv20) if e and ok(e.atm_iv) and ok(s.hv20) and s.hv20 else 'n/a'}</td>"
            f'<td class="l {cls}">{_e(LEAN_LABELS[w.lean])}</td></tr>')
    table = ('<div class="card scroll"><table><tr><th class="l">หุ้น</th><th>ราคา</th><th>สัปดาห์ขึ้น (อดีต)</th>'
             "<th>โมเดล P(ขึ้น)</th><th>โมเดลผ่านทดสอบ</th><th>ตลาดออปชั่น P(ขึ้น)</th><th>กรอบ ±1 SD</th>"
             f'<th>IV/HV20</th><th class="l">สรุป</th></tr>{"".join(body)}</table></div>')
    return ('<!doctype html><html lang="th"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Weekly Options Scan</title><style>{CSS}</style></head><body><main>"
            "<h1>สรุปความน่าจะเป็นรายสัปดาห์</h1>"
            f'<div class="sub">จากราคาล่าสุดไปอีก 5 วันทำการ | สร้างเมื่อ '
            f'{_e(cal.stamp(rows[0].generated_at)) if rows else ""}</div>' + table
            + f'<p class="note">{_e(DISCLAIMER)}</p></main></body></html>')
