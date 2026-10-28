"""อ่านการตั้งค่าจาก config.toml (ค่าที่ไม่ได้เขียนไว้ใช้ค่าเริ่มต้น)"""

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class BarcodePatterns:
    work_order: str = r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}[A-Z0-9]{2,4}$"
    mat_do: str = r"^OP[0-9A-Z]{8,14}$"
    mat_coil: str = r"^OF[0-9A-Z]{8,14}$"
    die: str = r"^DIE\.\d{1,3}$"


@dataclass
class Options:
    confirm_before_final_enter: bool = True
    lot_qty_includes_ng: bool = True
    step_timeout_seconds: float = 15.0
    home_keys: list = field(default_factory=list)


@dataclass
class Config:
    mode: str = "demo"
    session: str = "A"
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = Path("data")
    shifts: dict = field(default_factory=lambda: {"A": "08:00", "B": "16:00", "C": "00:00"})
    colors: list = field(default_factory=lambda: ["ชมพู", "เขียว"])
    process_colors: dict = field(default_factory=dict)
    options: Options = field(default_factory=Options)
    barcodes: BarcodePatterns = field(default_factory=BarcodePatterns)


MODES = ("demo", "pcomm")
TABLES = ("shifts", "process_colors")
SECTIONS = {"options": Options, "barcodes": BarcodePatterns}


def _check_type(name, value, default):
    expected = type(default)
    if isinstance(default, Path):
        expected = str
    ok = isinstance(value, expected) and not (expected is int and isinstance(value, bool))
    if expected is float and isinstance(value, int) and not isinstance(value, bool):
        ok = True
    if not ok:
        raise ConfigError(f"ค่า '{name}' ต้องเป็น {expected.__name__} แต่ได้ {value!r}")
    return float(value) if expected is float else value


def _apply_section(target, table, section):
    known = {f.name for f in fields(target)}
    for key, value in table.items():
        if key not in known:
            raise ConfigError(f"ไม่รู้จักค่า '{key}' ในหมวด [{section}]")
        setattr(target, key, _check_type(f"{section}.{key}", value, getattr(target, key)))


def load_config(path) -> Config:
    path = Path(path)
    config = Config()
    raw = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(f"{path.name} เขียนผิดรูปแบบ: {error}") from None

    simple = {f.name for f in fields(Config)} - set(TABLES) - set(SECTIONS)
    for key, value in raw.items():
        if key in SECTIONS:
            if not isinstance(value, dict):
                raise ConfigError(f"[{key}] ต้องเป็นหมวด")
            _apply_section(getattr(config, key), value, key)
        elif key in TABLES:
            if not isinstance(value, dict):
                raise ConfigError(f"[{key}] ต้องเป็นหมวด")
            setattr(config, key, {str(k): str(v) for k, v in value.items()})
        elif key in simple:
            setattr(config, key, _check_type(key, value, getattr(config, key)))
        else:
            raise ConfigError(f"ไม่รู้จักค่า '{key}' ใน {path.name}")

    config.data_dir = path.parent / Path(config.data_dir)
    _validate(config)
    return config


def _validate(config: Config):
    if config.mode not in MODES:
        raise ConfigError(f"mode ต้องเป็น {' หรือ '.join(MODES)} แต่ได้ '{config.mode}'")
    if not config.shifts:
        raise ConfigError("[shifts] ต้องมีอย่างน้อย 1 กะ")
    for name, start in config.shifts.items():
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", start):
            raise ConfigError(f"เวลาเริ่มกะ {name} ต้องเป็นรูปแบบ HH:MM แต่ได้ '{start}'")
    if not config.colors:
        raise ConfigError("colors ต้องมีอย่างน้อย 1 สี")
    for name in ("work_order", "mat_do", "mat_coil", "die"):
        try:
            re.compile(getattr(config.barcodes, name))
        except re.error as error:
            raise ConfigError(f"barcodes.{name} เขียน regular expression ผิด: {error}") from None
