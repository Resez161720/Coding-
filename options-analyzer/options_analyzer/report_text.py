"""Thai plain-text report for the terminal."""
from __future__ import annotations

from . import calendar_us as cal
from .analysis import AnalysisResult
from .contracts import ContractEval
from .fmt import DISCLAIMER, STATUS_TH, earnings_note, money, num, ok, pct, vol_points
from .validation import FAIL, PASS, WARN
from .weekly import FEATURE_LABELS, LEAN_LABELS

LINE = "=" * 78
SUB = "-" * 78


def _validation(res: AnalysisResult, verbose: bool) -> list[str]:
    v = res.validation
    out = [f"[1] ผลตรวจสอบข้อมูล: ผ่าน {v.count(PASS)} | เตือน {v.count(WARN)} | ไม่ผ่าน {v.count(FAIL)}"]
    for c in v.checks:
        if verbose or c.status != PASS:
            out.append(f"    [{STATUS_TH[c.status]}] {c.area} / {c.name}: {c.detail}")
    if not verbose and v.count(PASS):
        out.append("    (รายการที่ผ่านทั้งหมดดูได้ด้วย --verbose หรือในรายงาน HTML)")
    return out


def _stock(res: AnalysisResult) -> list[str]:
    s = res.stock
    t = f" ณ {s.spot_time:%Y-%m-%d %H:%M} ET" if s.spot_time else ""
    def side(level):
        if not ok(level):
            return "n/a"
        return f"{num(level)} ({'เหนือ' if s.spot > level else 'ใต้'})"
    out = [
        "[2] ภาพรวมหุ้น",
        f"    ราคา {num(s.spot)}{t} | 1 วัน {pct(s.change_1d, 2, True)} | 5 วัน {pct(s.change_5d, 2, True)} "
        f"| 1 เดือน {pct(s.change_21d, 2, True)}",
        f"    กรอบ 52 สัปดาห์ {num(s.low_52w)} – {num(s.high_52w)} | Max drawdown 1 ปี {pct(s.max_drawdown_1y)}",
        f"    ราคาเทียบเส้นค่าเฉลี่ย: SMA20 {side(s.sma20)} | SMA50 {side(s.sma50)} | SMA200 {side(s.sma200)}",
        f"    RSI(14) {num(s.rsi14, 1)} | ATR(14) {pct(s.atr14_pct)} ต่อวัน | Beta 1 ปี (vs SPY) {num(s.beta_1y)}",
        f"    ความผันผวนจริง (HV): 20 วัน {pct(s.hv20)} | 60 วัน {pct(s.hv60)} | 1 ปี {pct(s.hv252)} "
        f"| HV20 อยู่ที่ percentile {num(s.hv20_percentile, 0)} ของ 1 ปี",
    ]
    mk = []
    if res.vix is not None:
        mk.append(f"VIX {num(res.vix, 1)}" + (" (ตลาดกลัวสูง)" if res.vix >= 30 else ""))
    if res.spy_above_sma200 is not None:
        mk.append("SPY อยู่" + ("เหนือ" if res.spy_above_sma200 else "ใต้") + " SMA200")
    if mk:
        out.append("    ตลาดโดยรวม: " + " | ".join(mk))
    return out


def _weekly(res: AnalysisResult) -> list[str]:
    w = res.weekly
    if w is None:
        return ["[3] แนวโน้มรายสัปดาห์: คำนวณไม่ได้"]
    out = [
        "[3] ความน่าจะเป็นรายสัปดาห์ (จากราคาล่าสุดไปอีก 5 วันทำการ)",
        f"    สถิติฐาน: สัปดาห์ที่ปิดบวก {pct(w.base_up_rate)} จาก {w.n_weeks} สัปดาห์ "
        f"(ช่วงเชื่อมั่น 95%: {pct(w.base_ci[0], 0)}–{pct(w.base_ci[1], 0)}) | 2 ปีล่าสุด {pct(w.recent_up_rate)} "
        f"({w.recent_n} สัปดาห์)",
        f"    ขนาดการเคลื่อนไหวต่อสัปดาห์: มัธยฐาน ±{pct(w.abs_move_pct['median'])} | 75% ของสัปดาห์ไม่เกิน "
        f"±{pct(w.abs_move_pct['p75'])} | 90% ไม่เกิน ±{pct(w.abs_move_pct['p90'])}",
        "    โอกาสเคลื่อนไหวเกิน: " + " | ".join(f"±{x:.0%} = {pct(p)}" for x, p in w.prob_abs_move_gt.items()),
        f"    สัปดาห์ขึ้นเฉลี่ย {pct(w.avg_up_move, 2, True)} | สัปดาห์ลงเฉลี่ย {pct(w.avg_down_move, 2, True)}",
    ]
    if w.conditionals:
        out.append("    สถานการณ์คล้ายปัจจุบันในอดีต → สัปดาห์ถัดไปปิดบวก:")
        for c in w.conditionals:
            flag = " *ต่างจากค่าเฉลี่ยอย่างมีนัยสำคัญ" if c.differs_from_base else ""
            out.append(f"      - {c.label}: {c.condition} → {pct(c.up_rate)} (n={c.n}, CI {pct(c.ci[0], 0)}–"
                       f"{pct(c.ci[1], 0)}){flag}")
    if w.model is not None:
        m = w.model
        out.append(f"    โมเดลสถิติ (logistic regression, ทดสอบแบบ walk-forward): P(ขึ้น) = {pct(m.prob_up)}")
        out.append(f"      ความแม่นยำนอกตัวอย่าง {pct(m.accuracy)} เทียบการเดาด้วยค่าเฉลี่ย {pct(m.naive_accuracy)}")
        out.append(f"      {w.model_note}")
        out.append("      ตัวแปรที่ใช้: " + ", ".join(FEATURE_LABELS.get(f, f) for f in m.features_used))
    elif w.model_note:
        out.append(f"    โมเดลสถิติ: {w.model_note}")
    if res.selected is not None and ok(res.selected.implied_prob_up):
        out.append(f"    ตลาดออปชั่นประเมิน (risk-neutral): P(ราคา > {num(res.selected.spot)} ณ "
                   f"{res.selected.expiry}) = {pct(res.selected.implied_prob_up)}")
    out.append(f"    >> สรุปทิศทางสัปดาห์หน้า: {LEAN_LABELS[w.lean]}")
    out.append(f"       เหตุผล: {w.lean_reason}")
    return out


def _options(res: AnalysisResult) -> list[str]:
    e = res.selected
    if e is None:
        return []
    s = res.stock
    out = [f"[4] ออปชั่นหมดอายุ {e.expiry} ({e.dte} วัน / เหลือ {e.sessions} วันทำการ)"]
    if res.valuation_time is not None and res.valuation_time != res.generated_at:
        out.append(f"    ตลาดปิดอยู่: ราคาหุ้นและออปชั่นเป็นราคา ณ ปิดตลาด {res.valuation_time:%Y-%m-%d %H:%M} ET "
                   "และคำนวณเวลาถึงวันหมดอายุจากจุดนั้น")
    em = e.expected_move_iv
    out.append(f"    ATM IV {pct(e.atm_iv)} | IV ÷ HV20 = {num(e.atm_iv / s.hv20 if ok(s.hv20) and s.hv20 else float('nan'))} "
               f"| Skew 25Δ (Put−Call) {vol_points(e.skew_25d)}")
    if ok(em):
        out.append(f"    กรอบราคาคาดการณ์ ±1 SD (ตาม IV): ±{num(em)} (±{pct(em / e.spot)}) → {num(e.spot - em)} – "
                   f"{num(e.spot + em)}  (ราคาจะอยู่ในกรอบนี้ราว 68% ของเวลา)")
    if e.straddle_price is not None:
        out.append(f"    ราคา Straddle ATM (strike {num(e.straddle_strike)}): {num(e.straddle_price)} "
                   f"(ตลาดคาดการเคลื่อนไหว ±{pct(e.straddle_price / e.spot)})")
        if ok(e.hist_prob_exceed_straddle):
            verdict = ("ออปชั่นค่อนข้างแพงเมื่อเทียบกับอดีต" if e.hist_prob_exceed_straddle < 0.45 else
                       "ออปชั่นค่อนข้างถูกเมื่อเทียบกับอดีต" if e.hist_prob_exceed_straddle > 0.55 else
                       "ราคาใกล้เคียงกับการเคลื่อนไหวในอดีต")
            out.append(f"      ในอดีต 5 ปี ราคาเคลื่อนไหวใน {e.sessions} วันทำการเกินระดับนี้ "
                       f"{pct(e.hist_prob_exceed_straddle)} ของครั้ง → {verdict}")
    out.append(f"    Put/Call Open Interest {num(e.put_call_oi)} | Put/Call Volume {num(e.put_call_volume)}")
    if res.term:
        out.append("    โครงสร้าง IV ตามวันหมดอายุ: " + " | ".join(f"{d:%m-%d} {pct(iv)}" for d, _, iv in res.term))
    earn = res.earnings
    if earn is not None:
        if earn.status == "none":
            out.append("    งบการเงิน: ไม่มี (ETF/ดัชนี)")
        elif earn.upcoming:
            out.append(f"    ประกาศงบครั้งถัดไป: {earn.upcoming[0]} ({earnings_note(earn.confirmed)})")
        else:
            out.append("    ประกาศงบครั้งถัดไป: ยืนยันไม่ได้ — โปรดตรวจสอบเองก่อนซื้อ")
    if res.earnings_moves:
        moves = [abs(m) for _, m in res.earnings_moves]
        out.append(f"    การเคลื่อนไหวหลังประกาศงบ {len(moves)} ครั้งล่าสุด: เฉลี่ย ±{pct(sum(moves) / len(moves))} "
                   f"(" + ", ".join(f"{d:%Y-%m-%d}: {m:+.1%}" for d, m in res.earnings_moves) + ")")
    return out


def _table(cands: list[ContractEval]) -> list[str]:
    if not cands:
        return []
    out = ["[5] สัญญาใกล้ ATM (ประเมินสำหรับฝั่งผู้ซื้อ)",
           "    ประเภท  Strike    ราคา   Spread   IV    Delta  จุดคุ้มทุน(%)  กำไร%(IV) กำไร%(อดีต) เสียหมด%  Theta/วัน  ความเสี่ยง"]
    for ev in cands:
        out.append(
            f"    {ev.kind.upper():5} {ev.strike:8.2f} {ev.price:7.2f} {pct(ev.spread_pct):>7} {pct(ev.iv):>6} "
            f"{ev.delta:+6.2f} {num(ev.breakeven):>8}({pct(ev.breakeven_move, 1, True):>6}) {pct(ev.prob_profit):>8} "
            f"{pct(ev.prob_profit_hist.prob):>10} {pct(1 - ev.prob_itm):>8} {pct(ev.theta_pct):>9}  "
            f"{ev.risk_level} ({ev.risk_score:.0f})")
    out.append("    กำไร% = โอกาสที่ราคา ณ วันหมดอายุเกินจุดคุ้มทุน | เสียหมด% = โอกาสหมดอายุไร้ค่า (OTM)")
    return out


def contract_detail(ev: ContractEval, title: str) -> list[str]:
    hp = ev.prob_profit_hist
    out = [
        f"[6] {title}: {ev.kind.upper()} strike {ev.strike:g} หมดอายุ {ev.expiry} ({ev.contract})",
        f"    ราคา {num(ev.price)} ({'ราคากลาง bid/ask' if ev.price_source == 'mid' else 'ราคาซื้อขายล่าสุด'}; "
        f"bid {num(ev.bid)} / ask {num(ev.ask)}) → ต้นทุน {money(ev.cost)} ต่อสัญญา = ขาดทุนสูงสุด",
        f"    จุดคุ้มทุน ณ วันหมดอายุ {num(ev.breakeven)} (หุ้นต้องเคลื่อนที่ {pct(ev.breakeven_move, 2, True)})",
        f"    IV {pct(ev.iv)} | Delta {ev.delta:+.3f} | Gamma {ev.gamma:.4f} | Theta {money(ev.theta * 100)}/วัน/สัญญา "
        f"| Vega {money(ev.vega * 100)}/1 จุด IV/สัญญา",
        "    ความน่าจะเป็น ณ วันหมดอายุ:",
        f"      - มีกำไร (ตาม IV ของตลาด): {pct(ev.prob_profit)}",
        f"      - มีกำไร (จากการเคลื่อนไหวจริงย้อนหลัง 5 ปี): {pct(hp.prob)} "
        f"(CI {pct(hp.ci_low, 0)}–{pct(hp.ci_high, 0)}, {hp.n:,} ช่วงเวลา)",
        f"      - กำไร ≥ 100% (ราคาออปชั่นเพิ่มเป็น 2 เท่า): {pct(ev.prob_double)}",
        f"      - หมดอายุไร้ค่า (เสียเงินทั้งหมด): {pct(1 - ev.prob_itm)}",
        f"      - ราคาแตะ strike ก่อนหมดอายุ (โดยประมาณ): {pct(ev.prob_touch)}",
        "    เกณฑ์ความเสี่ยง:",
    ]
    for c in ev.criteria:
        out.append(f"      [{STATUS_TH[c.status]:^6}] {c.name}: {c.value}")
        out.append(f"               เกณฑ์: {c.rule}")
    out.append(f"    >> ระดับความเสี่ยง: {ev.risk_level} (คะแนน {ev.risk_score:.0f}/100 — ยิ่งสูงยิ่งเสี่ยง)")
    out.append("       ระดับนี้ใช้เปรียบเทียบระหว่างสัญญา การซื้อออปชั่นมีโอกาสเสียเงินทั้งหมดเสมอ")
    return out


def render(res: AnalysisResult, verbose: bool = False) -> str:
    name = res.stock.name if res.stock else res.ticker
    out = [LINE, f" รายงานวิเคราะห์ก่อนซื้อออปชั่น: {res.ticker} — {name}",
           f" สร้างเมื่อ {cal.stamp(res.generated_at)} | ข้อมูล Yahoo Finance | "
           f"อัตราดอกเบี้ย {pct(res.r, 2)} | ปันผล {pct(res.q, 2)}", LINE]
    out += _validation(res, verbose)
    for e in res.errors:
        out.append(f"    !! {e}")
    for n in res.notes:
        out.append(f"    หมายเหตุ: {n}")
    if res.stock is not None:
        out += ["", *_stock(res), "", *_weekly(res)]
    if res.selected is not None:
        out += ["", *_options(res)]
    if res.candidates:
        out += ["", *_table(res.candidates)]
    if res.focus is not None:
        out += ["", *contract_detail(res.focus, "สัญญาที่คุณเลือก")]
    out += ["", SUB, "ข้อควรทราบ: " + DISCLAIMER, LINE]
    return "\n".join(out)


def render_scan(rows: list[AnalysisResult]) -> str:
    out = [LINE, " สรุปความน่าจะเป็นรายสัปดาห์ (5 วันทำการข้างหน้า)", LINE,
           f" {'หุ้น':6} {'ราคา':>9} {'ขึ้น%(อดีต)':>11} {'โมเดล':>7} {'ผ่านทดสอบ':>9} {'ตลาดออปชั่น':>11} "
           f"{'กรอบ±(IV)':>9} {'IV/HV':>6}  สรุป"]
    for res in rows:
        if res.stock is None or res.weekly is None:
            out.append(f" {res.ticker:6} ข้อมูลไม่ผ่านการตรวจสอบ: {'; '.join(res.errors) or 'ไม่ทราบสาเหตุ'}")
            continue
        w, s, e = res.weekly, res.stock, res.selected
        m = w.model
        em = pct(e.expected_move_iv / e.spot) if e and ok(e.expected_move_iv) else "n/a"
        ivhv = num(e.atm_iv / s.hv20) if e and ok(e.atm_iv) and ok(s.hv20) and s.hv20 else "n/a"
        out.append(
            f" {res.ticker:6} {num(s.spot):>9} {pct(w.base_up_rate):>11} {pct(m.prob_up) if m else 'n/a':>7} "
            f"{('ใช่' if m and m.validated else 'ไม่'):>9} {pct(e.implied_prob_up) if e else 'n/a':>11} "
            f"{em:>9} {ivhv:>6}  {LEAN_LABELS[w.lean]}")
        warn = res.validation.count(WARN)
        if warn or res.errors:
            out.append(f"        (เตือน {warn} รายการ{'; ' + '; '.join(res.errors) if res.errors else ''})")
    out += [SUB, "ผ่านทดสอบ = โมเดลแม่นกว่าการเดาด้วยค่าเฉลี่ยในอดีตอย่างมีนัยสำคัญเมื่อทดสอบนอกตัวอย่าง",
            "ตลาดออปชั่น = ความน่าจะเป็นแบบ risk-neutral ที่ราคาจะสูงกว่าปัจจุบัน ณ วันหมดอายุที่เลือก",
            "ข้อควรทราบ: " + DISCLAIMER, LINE]
    return "\n".join(out)
