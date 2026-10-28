"""บันทึกหน้าจอเขียวเป็นไฟล์ข้อความ (ข้อความทุกแถว + ตำแหน่งช่อง) ไว้ตรวจหรือส่งให้ผู้พัฒนา"""

from datetime import datetime
from pathlib import Path


def write_dump(screen, folder, note="") -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = folder / f"screen-{stamp}.txt"
    lines = [f"# {note}" if note else "# screen dump", f"# cursor={screen.cursor} inhibited={screen.input_inhibited}", ""]
    lines += [f"{number:02d}|{row}|" for number, row in enumerate(screen.rows, start=1)]
    lines += ["", "# fields: row,col,length,protected,numeric,text"]
    lines += [f"{f.row},{f.col},{f.length},{int(f.protected)},{int(f.numeric)},{f.text!r}" for f in screen.fields]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
