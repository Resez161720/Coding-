#!/usr/bin/env python3
"""สร้างวิดีโอนำพากย์ (teleprompter) แนวตั้ง 9:16 จาก script.md

ใช้: python3 build_guide.py
ผลลัพธ์: guide/twd_guide_full.mp4 และ guide/chapters.md
"""
import re
import subprocess
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "script.md"
OUT_DIR = HERE / "guide"
ASS_FILE = OUT_DIR / "guide.ass"
VIDEO = OUT_DIR / "twd_guide_full.mp4"
CHAPTERS = OUT_DIR / "chapters.md"

READ_RATE = 12.0      # ตัวอักษรต่อวินาที (ไม่นับช่องว่าง) ความเร็วพากย์ที่อ่านสบาย
CHUNK_PAD = 0.35      # เวลาหายใจท้ายแต่ละท่อน
ELLIPSIS_PAD = 0.5    # เว้นจังหวะเพิ่มเมื่อท่อนจบด้วย "…"
SECTION_CARD = 1.5    # การ์ดชื่อหัวข้อก่อนเริ่มแต่ละหัวข้อ
COUNTDOWN = 3
END_CARD = 2.0
LINE_WIDTH = 28       # ความกว้างสูงสุดต่อบรรทัดของข้อความหลัก (นับเฉพาะตัวที่กินที่)
NEXT_LINE_WIDTH = 40
SCENE_LINE_WIDTH = 44


def width(text):
    """ความกว้างโดยประมาณ: ไม่นับสระบน/ล่างและวรรณยุกต์ (combining marks)"""
    return sum(1 for ch in text if not unicodedata.category(ch).startswith("M"))


def is_thai(word):
    return any("฀" <= ch <= "๿" for ch in word)


def break_penalty(left, right):
    """ตัดบรรทัดได้ดีเฉพาะหลังจุลภาค หรือระหว่างวลีไทยสองวลี
    ห้ามตัดก่อน "ๆ" และไม่ควรแยกชื่อภาษาอังกฤษ/ตัวเลขออกจากประโยคของมัน"""
    if right.startswith("ๆ"):
        return 10**6
    if left.endswith(","):
        return 0
    if is_thai(left) and is_thai(right):
        return 0
    return 400


def wrap(text, limit):
    """ตัดบรรทัดที่ช่องว่าง (ภาษาไทยไม่มีช่องว่างระหว่างคำ) ให้ได้บรรทัดน้อยที่สุด
    ยาวใกล้เคียงกัน และตัดตรงจุดที่อ่านเป็นธรรมชาติ"""
    words = text.split()
    n = len(words)
    best = [0.0] + [float("inf")] * n
    prev = [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(j):
            w = width(" ".join(words[i:j]))
            if w > limit and j - i > 1:
                continue
            cost = best[i] + 1000 + (limit - w) ** 2 / 10
            if i > 0:
                cost += break_penalty(words[i - 1], words[i])
            if cost < best[j]:
                best[j], prev[j] = cost, i
    lines, j = [], n
    while j > 0:
        lines.append(" ".join(words[prev[j]:j]))
        j = prev[j]
    return lines[::-1]


def chunk(narration):
    """แบ่งบทพากย์เป็นท่อนตามเครื่องหมาย / ที่วางไว้ใน script.md"""
    return [c.strip() for c in narration.split("/") if c.strip()]


def clean_heading(h):
    h = re.sub(r"\(.*?\)", "", h)
    h = h.split("←")[0]
    h = "".join(ch for ch in h if ord(ch) < 0x1F000)
    return " ".join(h.split())


def parse_sections():
    sections, cur = [], None
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            cur = {"title": clean_heading(line[3:]), "narration": None, "scene": ""}
            sections.append(cur)
        elif cur and line.startswith("**🎙️ พากย์:**"):
            cur["narration"] = lines[i + 1].strip().strip('"')
        elif cur and line.startswith("**🎬 ภาพ:**"):
            cur["scene"] = line.split("**🎬 ภาพ:**", 1)[1].strip()
    return [s for s in sections if s["narration"]]


def ts(sec):
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def mmss(sec):
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def chunk_duration(text):
    d = len(text.replace(" ", "")) / READ_RATE + CHUNK_PAD
    if text.endswith("…"):
        d += ELLIPSIS_PAD
    return round(d, 2)


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Header,Loma,48,&H004848E0,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,8,60,60,220,1
Style: Main,Loma,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,5,60,60,0,1
Style: Card,Loma,84,&H004848E0,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,5,60,60,0,1
Style: Next,Loma,44,&H00888888,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,60,60,0,1
Style: Label,Loma,34,&H00666666,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,5,60,60,0,1
Style: Scene,Loma,38,&H0050D0F0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,60,60,230,1
Style: Bar,Loma,20,&H004848E0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def event(start, end, style, text, layer=0):
    return f"Dialogue: {layer},{ts(start)},{ts(end)},{style},,0,0,0,,{text}"


def main_text(text):
    return r"{\pos(540,860)}" + r"\N".join(wrap(text, LINE_WIDTH))


def next_text(text):
    return r"{\pos(540,1290)}" + r"\N".join(wrap(text, NEXT_LINE_WIDTH))


def scene_text(scene):
    return "ฉากที่ใส่: " + r"\N".join(wrap(scene, SCENE_LINE_WIDTH))


def bar(start, dur):
    """แถบนับถอยหลังใต้ข้อความหลัก หดจนหมดเมื่อถึงเวลาขึ้นท่อนถัดไป"""
    ms = int(dur * 1000)
    return event(start, start + dur, "Bar",
                 r"{\pos(140,1110)\p1\fscx100\t(0," + str(ms) + r",\fscx0)}m 0 0 l 800 0 800 10 0 10{\p0}")


def timeline(sections):
    """เวลาของทุกท่อนในวิดีโอนำพากย์ เรียงตามลำดับ: [(si, ci, text, start, dur)]
    คืนค่าเวลาที่ท่อนสุดท้ายจบด้วย build_part.py ใช้ค่านี้เทียบกับเสียงที่อัดตามวิดีโอนี้"""
    rows, t = [], float(COUNTDOWN)
    for si, sec in enumerate(sections):
        t += SECTION_CARD
        for ci, text in enumerate(chunk(sec["narration"])):
            d = chunk_duration(text)
            rows.append((si, ci, text, t, d))
            t += d
    return rows, t


def build():
    sections = parse_sections()
    rows, t_end = timeline(sections)
    events, chapters = [], []

    for n in range(COUNTDOWN):
        events.append(event(n, n + 1, "Card", r"{\pos(540,860)}" + str(COUNTDOWN - n)))
    events.append(event(0, COUNTDOWN, "Header", "เตรียมพากย์"))
    events.append(event(0, COUNTDOWN, "Label", r"{\pos(540,1210)}ท่อนแรก"))
    events.append(event(0, COUNTDOWN, "Next", next_text(rows[0][2])))

    for k, (si, ci, text, t, d) in enumerate(rows):
        sec = sections[si]
        if ci == 0:
            card = t - SECTION_CARD
            chapters.append((card, sec["title"]))
            events.append(event(card, t, "Card", main_text(sec["title"])))
            events.append(event(card, t, "Label", r"{\pos(540,1210)}ท่อนแรก"))
            events.append(event(card, t, "Next", next_text(text)))
            events.append(bar(card, SECTION_CARD))

        events.append(event(t, t + d, "Main", main_text(text)))
        events.append(bar(t, d))
        if k + 1 == len(rows):
            nxt = "จบ"
        elif rows[k + 1][0] != si:
            nxt = "▸ " + sections[rows[k + 1][0]]["title"]
        else:
            nxt = rows[k + 1][2]
        events.append(event(t, t + d, "Label", r"{\pos(540,1210)}ถัดไป"))
        events.append(event(t, t + d, "Next", next_text(nxt)))

        if k + 1 == len(rows) or rows[k + 1][0] != si:
            sec_start = chapters[-1][0]
            events.append(event(sec_start, t + d, "Header", sec["title"]))
            if sec["scene"]:
                events.append(event(sec_start, t + d, "Scene", scene_text(sec["scene"])))

    events.append(event(t_end, t_end + END_CARD, "Card", r"{\pos(540,860)}จบ"))
    t = t_end + END_CARD

    OUT_DIR.mkdir(exist_ok=True)
    ASS_FILE.write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")

    rows = "\n".join(f"| {mmss(s)} | {title} |" for s, title in chapters)
    CHAPTERS.write_text(
        "# เวลาเริ่มของแต่ละหัวข้อในวิดีโอนำพากย์\n\n"
        f"ความยาวรวม {mmss(t)} นาที (นับรวมนับถอยหลัง {COUNTDOWN} วินาทีตอนต้น)\n\n"
        "| เวลา | หัวข้อ |\n|---|---|\n" + rows + "\n",
        encoding="utf-8",
    )

    vf = f"vignette=PI/4,ass={ASS_FILE.name}"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c=0x141414:s=1080x1920:r=30:d={t:.2f}",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-vf", vf, "-shortest",
         "-c:v", "libx264", "-preset", "fast", "-crf", "26", "-tune", "stillimage",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
         "-movflags", "+faststart", VIDEO.name],
        cwd=OUT_DIR, check=True,
    )
    print(f"{VIDEO} ({mmss(t)})")
    for s, title in chapters:
        print(f"  {mmss(s)}  {title}")


if __name__ == "__main__":
    build()
