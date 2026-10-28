"""ตารางข้อมูลหลักในโฟลเดอร์ data (ไฟล์ CSV แก้ด้วย Excel ได้)

machines.csv   machine,name,color,multi_type,speed,action,route   (จำเป็น)
operators.csv  emp_no,name   (ถ้าไม่มีไฟล์ = ไม่ตรวจรายชื่อพนักงาน)
carts.csv      cart          (ถ้าไม่มีไฟล์ = ไม่ตรวจรายชื่อรถเข็น)
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

MACHINE_COLUMNS = ["machine", "name", "color", "multi_type", "speed", "action", "route"]


class MasterDataError(Exception):
    pass


@dataclass
class Machine:
    code: str
    name: str
    color: str
    multi_type: bool
    speed: str
    action: str
    route: int


@dataclass
class MasterData:
    machines: dict = field(default_factory=dict)
    operators: dict = field(default_factory=dict)
    carts: set = field(default_factory=set)


def _read(path: Path, required: list) -> list:
    # Excel บันทึกได้ทั้ง "CSV UTF-8" และ "CSV" ธรรมดา (ภาษาไทยเป็น cp874)
    try:
        return _read_with(path, required, "utf-8-sig")
    except UnicodeDecodeError:
        return _read_with(path, required, "cp874")


def _read_with(path: Path, required: list, encoding: str) -> list:
    with open(path, encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        columns = [name.strip() for name in (reader.fieldnames or [])]
        missing = [name for name in required if name not in columns]
        if missing:
            raise MasterDataError(f"{path.name}: ไม่มีคอลัมน์ {', '.join(missing)}")
        rows = []
        for row in reader:
            clean = {key.strip(): (value or "").strip() for key, value in row.items() if key}
            if any(clean.values()):
                rows.append(clean)
        return rows


def _yes(value: str) -> bool:
    return value.strip().upper() in {"Y", "YES", "TRUE", "1", "ใช่"}


def _load_machines(path: Path) -> dict:
    if not path.exists():
        raise MasterDataError(f"ไม่พบไฟล์ {path.name}")
    machines = {}
    for number, row in enumerate(_read(path, MACHINE_COLUMNS), start=2):
        code = row["machine"].upper()
        if not code:
            raise MasterDataError(f"{path.name} แถว {number}: ไม่มีรหัสเครื่อง")
        if code in machines:
            raise MasterDataError(f"{path.name}: รหัสเครื่อง {code} ซ้ำ")
        try:
            route = int(row["route"]) if row["route"] else 999
        except ValueError:
            raise MasterDataError(f"{path.name} แถว {number}: route ต้องเป็นตัวเลข") from None
        machines[code] = Machine(
            code=code,
            name=row["name"],
            color=row["color"],
            multi_type=_yes(row["multi_type"]),
            speed=row["speed"],
            action=row["action"].upper(),
            route=route,
        )
    return machines


def load_masterdata(data_dir) -> MasterData:
    data_dir = Path(data_dir)
    master = MasterData(machines=_load_machines(data_dir / "machines.csv"))
    operators = data_dir / "operators.csv"
    if operators.exists():
        master.operators = {row["emp_no"].upper(): row["name"] for row in _read(operators, ["emp_no", "name"])}
    carts = data_dir / "carts.csv"
    if carts.exists():
        master.carts = {row["cart"].upper() for row in _read(carts, ["cart"])}
    return master
