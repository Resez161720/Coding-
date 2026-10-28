"""เริ่มโปรแกรม: py -3-32 -m tagbot [--config config.toml] [--no-browser]"""

import argparse
import logging
import sys
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .app import App
from .config import ConfigError, load_config
from .demo import demo_driver
from .web import make_server

ROOT = Path(__file__).resolve().parent.parent


def setup_logging(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "tagbot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[handler, logging.StreamHandler()])


def driver_factory(config):
    if config.mode == "demo":
        return demo_driver

    def connect():
        from .driver.pcomm import PcommDriver
        return PcommDriver(config.session)

    return connect


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tagbot", description="ระบบช่วยพิมพ์ Tag")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--no-browser", action="store_true", help="ไม่ต้องเปิดเบราว์เซอร์ให้อัตโนมัติ")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"config.toml มีปัญหา: {error}")
        return 2

    setup_logging(config.data_dir.parent / "logs")
    host = "127.0.0.1" if config.host in ("0.0.0.0", "") else config.host
    url = f"http://{host}:{config.port}/"
    app = App(config, driver_factory(config))
    try:
        server = make_server(app, config.host, config.port)
    except OSError:
        app.shutdown()
        print(f"เปิดพอร์ต {config.port} ไม่ได้ อาจเปิดโปรแกรมซ้ำอยู่แล้ว ลองเปิด {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 1

    mode = "โหมดทดลอง (จอเขียวจำลอง)" if config.mode == "demo" else f"เชื่อมต่อจอเขียว session {config.session}"
    print(f"ระบบช่วยพิมพ์ Tag - {mode}")
    print(f"เปิดหน้าจอที่ {url}  (ปิดหน้าต่างนี้หรือกด Ctrl+C เพื่อหยุดโปรแกรม)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
