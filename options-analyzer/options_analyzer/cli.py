"""Command line interface.

    python -m options_analyzer AAPL
    python -m options_analyzer AAPL --expiry 2026-10-23 --call 250
    python -m options_analyzer scan AAPL NVDA TSLA SPY
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import webbrowser
from pathlib import Path

from . import report_html, report_text
from .analysis import analyze


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _write_html(content: str, path: str | None, default_name: str, open_it: bool) -> Path:
    out = Path(path) if path else Path("reports") / default_name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    if open_it:
        webbrowser.open(out.resolve().as_uri())
    return out


def _provider():
    from .data import YahooProvider

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return YahooProvider()


def cmd_analyze(args) -> int:
    if args.call is not None and args.put is not None:
        print("เลือกได้ทีละสัญญา: ใช้ --call หรือ --put อย่างใดอย่างหนึ่ง", file=sys.stderr)
        return 2
    focus = ("call", args.call) if args.call is not None else ("put", args.put) if args.put is not None else None
    print(f"กำลังดึงและตรวจสอบข้อมูล {args.ticker.upper()} ...", file=sys.stderr)
    res = analyze(args.ticker, _provider(), expiry=args.expiry, focus=focus, min_dte=args.min_dte)
    print(report_text.render(res, verbose=args.verbose))
    if not args.no_html:
        stamp = res.generated_at.strftime("%Y%m%d_%H%M")
        path = _write_html(report_html.render(res), args.html, f"{res.ticker}_{stamp}.html", args.open)
        print(f"\nรายงาน HTML พร้อมกราฟ: {path.resolve()}")
    return 1 if res.errors else 0


def cmd_scan(args) -> int:
    provider = _provider()
    results = []
    for t in args.tickers:
        print(f"กำลังวิเคราะห์ {t.upper()} ...", file=sys.stderr)
        results.append(analyze(t, provider, min_dte=args.min_dte, term_n=0, per_side=0))
    print(report_text.render_scan(results))
    if not args.no_html:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
        path = _write_html(report_html.render_scan(results), args.html, f"scan_{stamp}.html", args.open)
        print(f"\nรายงาน HTML: {path.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="options_analyzer",
                                description="วิเคราะห์ความเสี่ยงก่อนซื้อออปชั่นหุ้นสหรัฐ (ข้อมูล Yahoo Finance)")
    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("analyze", help="วิเคราะห์หุ้น 1 ตัว และสัญญาออปชั่น")
    a.add_argument("ticker", help="ชื่อย่อหุ้น เช่น AAPL")
    a.add_argument("--expiry", help="วันหมดอายุ YYYY-MM-DD (ค่าเริ่มต้น: วันหมดอายุแรกที่ห่างอย่างน้อย --min-dte วัน)")
    a.add_argument("--call", type=float, metavar="STRIKE", help="ประเมิน Call ที่ strike นี้แบบละเอียด")
    a.add_argument("--put", type=float, metavar="STRIKE", help="ประเมิน Put ที่ strike นี้แบบละเอียด")
    a.add_argument("--min-dte", type=int, default=4, help="จำนวนวันขั้นต่ำถึงวันหมดอายุเมื่อเลือกอัตโนมัติ (ค่าเริ่มต้น 4)")
    a.add_argument("--html", help="ที่เก็บไฟล์ HTML (ค่าเริ่มต้น reports/<TICKER>_<เวลา>.html)")
    a.add_argument("--no-html", action="store_true", help="ไม่สร้างไฟล์ HTML")
    a.add_argument("--open", action="store_true", help="เปิดรายงาน HTML ในเบราว์เซอร์")
    a.add_argument("--verbose", action="store_true", help="แสดงรายการตรวจสอบข้อมูลทั้งหมด")
    a.set_defaults(func=cmd_analyze)

    s = sub.add_parser("scan", help="สรุปความน่าจะเป็นรายสัปดาห์ของหลายหุ้น")
    s.add_argument("tickers", nargs="+")
    s.add_argument("--min-dte", type=int, default=4)
    s.add_argument("--html")
    s.add_argument("--no-html", action="store_true")
    s.add_argument("--open", action="store_true")
    s.set_defaults(func=cmd_scan)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ("analyze", "scan", "-h", "--help"):
        argv.insert(0, "analyze")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
