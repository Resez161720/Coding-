#!/usr/bin/env python3
"""ตัดต่อคลิป TikTok หนึ่งพาร์ทจากเสียงพากย์ที่อัดตามวิดีโอนำพากย์

ใช้: python3 build_part.py <เลขพาร์ท> <ไฟล์เสียง> [ไฟล์หนังสำหรับภาพประกอบ]
ผลลัพธ์ใน part<N>/: twd_part<N>.mp4, voice_part<N>_clean.m4a, part<N>.srt
ถ้าไม่ใส่ไฟล์หนัง พื้นหลังจะเป็นสีเข้มอย่างเดียว (ไฟล์หนังดาวน์โหลดได้จาก FILM["url"])

ขั้นตอน
1. หาช่วงที่มีเสียงพูดจากระดับเสียง แล้วจับคู่จุดเริ่มพูดแต่ละช่วงกับท่อนในสคริปต์
   โดยใช้เวลาของท่อนในวิดีโอนำพากย์เป็นตัวตั้ง (ผู้พากย์อ่านตามวิดีโอนั้น)
2. ตัดเสียงเฉพาะช่วงของพาร์ทนี้ ย่นช่วงเงียบที่ยาวเกินไป ลดเสียงรบกวน และปรับความดัง
3. สร้างวิดีโอ 9:16 ที่มีคำบรรยายจากสคริปต์ตรงกับเสียง ข้อความ hook และการ์ดท้ายคลิป
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import build_guide as guide

HERE = Path(__file__).resolve().parent

PARTS = {
    1: {
        "sections": ["HOOK", "ปูเรื่อง", "ซีซั่น 1:", "ซีซั่น 2:"],
        "label": "PART 1/4 · ซีซั่น 1–2",
        # ข้อความบนจอ: (ท่อนที่เริ่มแสดง, ข้อความ) แสดงจนถึงข้อความถัดไปหรือจบหัวข้อ
        "banners": [
            ("ซีรีส์ซอมบี้ที่ฉายยาวถึง", "177 ตอน · สรุปครบใน 4 พาร์ท"),
            ("กลับไม่มีอยู่ในคอมิก", "เฉลยท้ายคลิป"),
            ("The Walking Dead ซีรีส์ของช่อง", "2010–2022 · 11 ซีซั่น"),
            ("กระซิบความลับบางอย่าง", "เขากระซิบอะไร?"),
            ("ทุกคนติดเชื้ออยู่แล้ว", "ทุกคนติดเชื้อแล้ว"),
        ],
        "end_card": [
            ("EndBig", "เฉลย: Daryl Dixon"),
            ("EndText", "ไม่มีในคอมิกต้นฉบับ"),
            ("EndText", "เป็นตัวละครที่สร้างขึ้นใหม่สำหรับซีรีส์"),
            ("EndGap", ""),
            ("EndNext", "PART 2 · ซีซั่น 3–5"),
            ("EndSmall", "เรือนจำ · The Governor · Terminus"),
            ("EndText", "กดติดตามไว้ ไม่พลาดตอนต่อไป"),
        ],
        # ภาพประกอบจาก FILM: (ท่อนที่เริ่มใช้ภาพนี้, เวลาในหนัง, ตำแหน่งครอปแนวนอน 0–1)
        # เวลาในหนังเป็นวินาทีเดียว (หาขอบเขตช็อตอัตโนมัติ) หรือ (เริ่ม, จบ) เมื่อต้องกำหนดช่วงเอง
        # ภาพนี้แสดงจนถึงท่อนของภาพถัดไป "END" คือพื้นหลังการ์ดท้ายคลิป
        # เลือกเฉพาะช็อตที่ไม่มีเลือด การทำร้าย หรือภาพเปลือยให้เห็น ช็อตที่อยู่ติดกับฉากแบบนั้น
        # กำหนดช่วงเองทุกครั้ง เพราะการหาจุดตัดฉากอัตโนมัติพลาดได้ในฉากมืด
        "broll": [
            ("ซีรีส์ซอมบี้ที่ฉายยาวถึง", 4338, 0.5),      # ฝูงซอมบี้เดินเข้าหากล้องตอนกลางคืน
            ("มีทั้งหมด 177 ตอน", 765, 0.5),              # หน้าซอมบี้ในความมืด
            ("แต่ตัวละครที่คนรักที่สุด", 4298, 0.5),       # ฝูงซอมบี้กลางทุ่ง
            ("กลับไม่มีอยู่ในคอมิก", 720, 0.4),            # ซอมบี้ข้างบ้าน
            ("The Walking Dead ซีรีส์ของช่อง", 3362, 0.5),  # โทรทัศน์
            ("ดัดแปลงมาจากคอมิก", 525, 0.5),             # ถนนชนบท
            ("ตอนแรกออกฉายคืนฮาโลวีน", 245, 0.5),         # สุสาน
            ("และจบในปี 2022", 1005, 0.5),                # ไฟหน้ารถกลางคืน
            ("วันนี้จะสรุปให้ฟัง", 2085, 0.6),              # กองไฟกลางคืน
            ("ตั้งแต่ซีซั่น 1", 4470, 0.5),                 # ซอมบี้เดินเข้าหากองไฟ
            ("รองนายอำเภอ Rick", 5475, 0.5),              # ตำรวจกับสุนัขกลางทุ่ง
            ("ตื่นจากโคม่า", 645, 0.5),                    # ห้องว่างในบ้านร้าง
            ("โลกที่เขาเคยรู้จัก", (2772.9, 2775.4), 0.5),   # ฝูงซอมบี้กลางทุ่งตอนกลางคืน
            ("เขาตามหาครอบครัว", (5516.4, 5521.8), 0.6),   # รถแล่นบนถนนลูกรัง
            ("ทั้งคู่อยู่กับ Shane", 1170, 0.5),           # บ้านตอนกลางคืน
            ("แต่สิ่งที่ Rick ไม่รู้", (4063.98, 4065.8), 0.5),  # ตอกไม้ปิดประตู (ก่อนตัดไปหน้านักแสดง)
            ("ระหว่างที่เขาโคม่า", 5370, 0.5),             # ต้นไม้ตัดกับท้องฟ้า
            ("และ Shane กับ Lori", (5375.3, 5378.4), 0.5),  # กิ่งไม้ตัดกับดวงอาทิตย์
            ("กลุ่มหนีไปถึงศูนย์ควบคุมโรค", 3540, 0.5),    # ข่าวเจ้าหน้าที่ที่วอชิงตัน
            ("และก่อนตึกจะระเบิด", 4321, 0.5),            # รถระเบิดเป็นไฟ
            ("หมอคนสุดท้ายที่นั่น", 3422, 0.5),            # ผู้ประกาศข่าว
            ("กระซิบความลับ", 2428, 0.5),                # หน้าปัดวิทยุ
            ("Sophia ลูกสาวของ Carol", 540, 0.5),         # ป่า
            ("Carl ถูกยิง", 5400, 0.4),                   # ชายถือปืนไรเฟิล
            ("กลุ่มต้องไปพักที่ฟาร์ม", 585, 0.55),          # บ้านไร่
            ("และค้นหา Sophia", 5580, 0.5),               # กลุ่มคนค้นหากลางทุ่ง
            ("จนเปิดประตูโรงนา", 4245, 0.7),              # โรงนา
            ("แล้วพบว่า Sophia", 3150, 0.5),              # เด็กหญิงนอนป่วย
            ("กลายเป็นซอมบี้อยู่ในนั้น", (5097.75, 5098.65), 0.5),  # เด็กหญิงที่กลายเป็นซอมบี้ (ก่อนฉากทำร้าย)
            ("ส่วน Rick กับ Shane", (4404.4, 4408.2), 0.5),  # ต่อสู้ (ภาพเบลอ ไม่เห็นหน้า)
            ("จน Rick ต้องฆ่า", (4424.9, 4426.3), 0.5),     # ต่อสู้ (ภาพเบลอ)
            ("แล้วเขาก็บอกทุกคนว่า", 3375, 0.5),           # โทรทัศน์ในห้อง
            ("หมอที่ CDC กระซิบ", 3436, 0.5),            # ผู้ประกาศข่าว
            ("ทุกคนติดเชื้ออยู่แล้ว", 1123, 0.4),          # ฝูงซอมบี้เดินตอนกลางคืน
            ("ไม่ว่าจะตายด้วยสาเหตุอะไร", (1063.8, 1065.8), 0.5),  # ร่างบนสนามหญ้าตอนกลางคืน
            ("ก็จะลุกขึ้นมาเป็นซอมบี้", 780, 0.5),          # ซอมบี้เดินเข้ามา
            ("END", (2775.4, 2777.6), 0.5),              # ฝูงซอมบี้ (เบลอ มืด) ช็อตถัดไปมีภาพเปลือย
        ],
    },
}

# หนังที่ใช้ทำภาพประกอบ เป็นสาธารณสมบัติในสหรัฐฯ (ไม่มีประกาศลิขสิทธิ์ตามกฎหมายปี 1909)
# เวลาใน "broll" อ้างอิงไฟล์นี้จาก Internet Archive
FILM = {
    "url": "https://archive.org/download/Night.Of.The.Living.Dead_1080p/NightOfTheLivingDead_PS3.mp4",
    "picture": "crop=1440:1080:240:0",     # ตัดขอบดำซ้ายขวาออก เหลือภาพ 4:3
    "credit": "ภาพประกอบ: Night of the Living Dead (1968) · สาธารณสมบัติ",
}
FPS = 30
MAX_SLOWMO = 2.5          # ถ้าช็อตสั้นกว่าเวลาที่ต้องใช้ ยืดได้ไม่เกินกี่เท่า
BROLL_LOOK = "eq=contrast=1.12:brightness=-0.07:saturation=0,drawbox=color=black@0.3:t=fill"
END_LOOK = "eq=contrast=1.05:brightness=-0.12:saturation=0,gblur=sigma=10,drawbox=color=black@0.4:t=fill"

SR = 16000
HOP = 160                 # 10 ms
MIN_GAP = 0.25            # ช่วงเงียบสั้นที่สุดที่ถือว่าเป็นจุดเว้นจังหวะ
MAX_PAUSE = 0.6           # ช่วงเงียบที่ยาวกว่านี้จะถูกย่น
KEEP_AFTER, KEEP_BEFORE = 0.2, 0.25
SNAP_WINDOW = 1.5         # จุดเริ่มพูดต้องห่างจากเวลาที่คาดไว้ไม่เกินนี้
SKIP_COST = 1.6           # มากกว่า SNAP_WINDOW เพื่อให้จับคู่เสมอเมื่ออยู่ในช่วงที่ยอมรับได้
DIP_COST = 0.6            # ช่วงเสียงตกสั้น ๆ (ไม่ถึงจุดหยุด) ใช้เป็นจุดเริ่มพูดสำรอง
TARGET_LUFS = -14.0      # ความดังที่นิยมสำหรับคลิปบนโซเชียล
LIMIT = 10 ** (-1.5 / 20)  # เพดานพีค -1.5 dBFS กันเสียงแตก
END_CARD = 5.0
CAPTION_WIDTH = 26


def load_audio(path):
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def speech_regions(audio):
    """ช่วงที่มีเสียงพูด ใช้เกณฑ์ที่ปรับตามระดับเสียงรบกวนของไฟล์นั้น
    คืนค่า (ช่วงที่รวมช่องว่างสั้น ๆ แล้ว, จุดเริ่มเสียงหลังช่วงเสียงตกสั้น ๆ, เกณฑ์ dB)"""
    n = len(audio) // HOP
    rms = np.sqrt(np.mean(audio[:n * HOP].reshape(n, HOP) ** 2, axis=1) + 1e-12)
    db = np.convolve(20 * np.log10(rms), np.ones(5) / 5, mode="same")
    p10, p90 = np.percentile(db, [10, 90])
    thr = p10 + 0.35 * (p90 - p10)
    speech = db > thr
    regions, i = [], 0
    while i < n:
        if speech[i]:
            j = i
            while j < n and speech[j]:
                j += 1
            regions.append([i / 100, j / 100])
            i = j
        else:
            i += 1
    dips = [b[0] for a, b in zip(regions, regions[1:]) if b[0] - a[1] >= 0.05]
    merged = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < 0.18:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [r for r in merged if r[1] - r[0] >= 0.08], dips, float(thr)


def align(targets, candidates):
    """จับคู่ท่อนกับจุดเริ่มพูดแบบเรียงลำดับ ให้ห่างจากเวลาที่คาดไว้น้อยที่สุด
    candidates คือ [(เวลา, ค่าปรับ)] เรียงตามเวลา ท่อนที่หาคู่ไม่ได้คืนค่า None"""
    onsets = [c[0] for c in candidates]
    n, m = len(targets), len(onsets)
    inf = float("inf")
    # best[k][j]: ต้นทุนต่ำสุดหลังจัด k ท่อน โดยใช้จุดเริ่มพูดถึงลำดับ j-1 แล้ว
    best = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for k in range(n):
        run, arg = inf, 0
        for j in range(m + 1):
            if best[k][j] < run:
                run, arg = best[k][j], j
            if best[k][j] + SKIP_COST < best[k + 1][j]:
                best[k + 1][j] = best[k][j] + SKIP_COST
                back[k + 1][j] = (j, None)
            if j < m:
                d = abs(onsets[j] - targets[k]) + candidates[j][1]
                if d <= SNAP_WINDOW and run + d < best[k + 1][j + 1]:
                    best[k + 1][j + 1] = run + d
                    back[k + 1][j + 1] = (arg, j)
    j = min(range(m + 1), key=lambda x: best[n][x])
    picks = [None] * n
    for k in range(n, 0, -1):
        j, used = back[k][j]
        picks[k - 1] = onsets[used] if used is not None else None
    return picks


def fill_gaps(picks, targets):
    out = list(picks)
    for k, p in enumerate(out):
        if p is None:
            lo = max([out[i] for i in range(k) if out[i] is not None] or [0.0])
            hi = min([x for x in picks[k + 1:] if x is not None] or [float("inf")])
            out[k] = min(max(targets[k], lo + 0.3), hi - 0.3)
    return out


def loudness(path):
    """ความดังเฉลี่ย (LUFS) และ true peak (dBFS) ของไฟล์เสียง"""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = log[log.rfind("Summary:"):]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"True peak:\s+Peak:\s+(-?[\d.]+) dBFS", summary).group(1))
    return lufs, peak


def keep_segments(regions, start, end):
    """ช่วงของไฟล์ต้นฉบับที่เก็บไว้ ช่วงเงียบที่ยาวเกิน MAX_PAUSE จะถูกย่น"""
    segs, cur = [], start
    inside = [r for r in regions if r[1] > start and r[0] < end]
    for a, b in zip(inside, inside[1:]):
        gap0, gap1 = a[1], b[0]
        if gap1 - gap0 > MAX_PAUSE and gap0 > start and gap1 < end:
            segs.append((cur, gap0 + KEEP_AFTER))
            cur = gap1 - KEEP_BEFORE
    segs.append((cur, end))
    return segs


def shot_bounds(film, t, before=8.0, after=10.0):
    """ช่วงเวลาของช็อตในหนังที่มีวินาที t อยู่ หาจากจุดตัดฉาก"""
    start = max(0.0, t - before)
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{before + after:.3f}",
         "-i", str(film), "-an", "-vf", f"{FILM['picture']},scale=320:-2,"
         "select='gt(scene,0.22)',showinfo", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    cuts = [start + float(x) for x in re.findall(r"pts_time:([\d.]+)", log)]
    return (max([c for c in cuts if c <= t] or [start]),
            min([c for c in cuts if c > t] or [start + before + after]))


def render_broll(film, plan, out_path, tmp):
    """plan: [(ภาพเริ่มที่เฟรม, จบที่เฟรม, วินาทีในหนัง, ครอป, ใช่การ์ดท้ายไหม)] ต่อกันเป็นวิดีโอเดียว"""
    files, report = [], []
    for i, (f0, f1, t, frac, is_end) in enumerate(plan):
        need = (f1 - f0) / FPS
        if isinstance(t, tuple):
            (s0, s1), margin, anchor = t, 0.0, (t[0] + t[1]) / 2
        else:
            (s0, s1), margin, anchor = shot_bounds(film, t), 0.06, t
        usable = s1 - s0 - 2 * margin
        if usable >= need:
            speed = 1.0
            src = min(max(anchor - need / 2, s0 + margin), s1 - margin - need)
        else:
            speed = min(need / usable, MAX_SLOWMO)
            src = s0 + margin
        x = round((2560 - 1080) * frac)
        look = END_LOOK if is_end else BROLL_LOOK
        clip = Path(tmp) / f"clip{i:03d}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{src:.3f}",
             "-t", f"{need / speed + 0.5:.3f}", "-i", str(film), "-an",
             "-vf", f"{FILM['picture']},scale=2560:1920,crop=1080:1920:{x}:0,"
                    f"setpts=(PTS-STARTPTS)*{speed:.4f},fps={FPS},{look},format=yuv420p",
             "-frames:v", str(f1 - f0), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             str(clip)], check=True)
        files.append(clip)
        report.append((f0 / FPS, t, src, need / speed, speed))
    listing = Path(tmp) / "clips.txt"
    listing.write_text("".join(f"file '{f}'\n" for f in files))
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c", "copy", str(out_path)], check=True)
    return report


def to_output(t, segs):
    acc = 0.0
    for a, b in segs:
        if t < a:
            return acc
        if t <= b:
            return acc + t - a
        acc += b - a
    return acc


def highlight(line):
    """ทำให้ชื่อตัวละคร ชื่อเฉพาะ และตัวเลขเป็นสีเหลือง"""
    out = []
    for w in line.split(" "):
        if any(ch.isascii() and ch.isalnum() for ch in w):
            out.append(r"{\c&H40D8FF&}" + w + r"{\c&HFFFFFF&}")
        else:
            out.append(w)
    return " ".join(out)


def srt_ts(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Loma,66,&H003030E0,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,6,0,1,3,0,5,0,0,0,1
Style: Label,Loma,38,&H00A0A0A0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: Credit,Loma,26,&H00909090,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: Badge,Loma,40,&H00FFFFFF,&H00FFFFFF,&H002828C8,&H00000000,1,0,0,0,100,100,0,0,3,12,0,5,0,0,0,1
Style: Caption,Loma,86,&H00FFFFFF,&H00FFFFFF,&H001A1A8A,&H00000000,1,0,0,0,100,100,0,0,1,5,0,5,60,60,0,1
Style: Banner,Loma,60,&H0040D8FF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,5,60,60,0,1
Style: EndBig,Loma,84,&H0040D8FF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,5,60,60,0,1
Style: EndText,Loma,50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,5,60,60,0,1
Style: EndNext,Loma,64,&H003030E0,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,5,60,60,0,1
Style: EndSmall,Loma,44,&H00A0A0A0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

POP = r"\fad(60,0)\fscx92\fscy92\t(0,140,\fscx100\fscy100)"


def build(part_no, voice_path, film=None):
    cfg = PARTS[part_no]
    out_dir = HERE / f"part{part_no}"
    out_dir.mkdir(exist_ok=True)

    sections = guide.parse_sections()
    rows, _ = guide.timeline(sections)
    wanted = [i for i, s in enumerate(sections)
              if any(s["title"].startswith(p) for p in cfg["sections"])]
    assert len(wanted) == len(cfg["sections"]), "หาหัวข้อของพาร์ทนี้ในสคริปต์ไม่ครบ"
    sel = [r for r in rows if r[0] in wanted]
    after = [r for r in rows if r[0] > wanted[-1]][:1]   # ท่อนแรกของพาร์ทถัดไป ใช้หาจุดตัดท้าย

    audio = load_audio(voice_path)
    regions, dips, thr_db = speech_regions(audio)
    onsets = [r[0] for i, r in enumerate(regions)
              if i == 0 or r[0] - regions[i - 1][1] >= MIN_GAP]
    candidates = sorted([(o, 0.0) for o in onsets] +
                        [(d, DIP_COST) for d in dips if min(abs(d - o) for o in onsets) > 0.05])

    guide_times = [r[3] for r in sel + after]
    diffs = [min(onsets, key=lambda o: abs(o - g)) - g for g in guide_times]
    lag = float(np.median([d for d in diffs if abs(d) < 2.0]))
    targets = [g + lag for g in guide_times]
    picks = align(targets, candidates)
    times = fill_gaps(picks, targets)
    snapped = sum(p is not None for p in picks[:len(sel)])

    cap_starts = times[:len(sel)]
    src_start = max(0.0, cap_starts[0] - 0.12)
    if after:
        nxt = times[len(sel)]
        last = max(r[1] for r in regions if r[1] < nxt - 0.1)
        src_end = min(last + 0.3, nxt - 0.05)
    else:
        src_end = regions[-1][1] + 0.3
    segs = keep_segments(regions, src_start, src_end)
    voice_len = sum(b - a for a, b in segs)

    # ---- เสียง ----
    chains, labels = [], []
    for i, (a, b) in enumerate(segs):
        d = b - a
        chains.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d=0.01,afade=t=out:st={d - 0.01:.3f}:d=0.01[s{i}]")
        labels.append(f"[s{i}]")
    clean = (";".join(chains) + ";" + "".join(labels) + f"concat=n={len(segs)}:v=0:a=1,"
             "highpass=f=80,afftdn=nr=20:nf=-56:tn=1,"
             # gate ลดเสียงรบกวนในช่วงหยุดพูด 20 dB ใช้เกณฑ์เดียวกับที่ใช้หาเสียงพูด
             f"agate=threshold={10 ** (thr_db / 20):.5f}:ratio=3:range=0.1:attack=5:release=200,"
             "aresample=44100[v]")
    clean_m4a = out_dir / f"voice_part{part_no}_clean.m4a"
    with tempfile.TemporaryDirectory() as tmp:
        raw, mastered = Path(tmp) / "raw.wav", Path(tmp) / "mastered.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(voice_path),
                        "-filter_complex", clean, "-map", "[v]", str(raw)], check=True)
        # เสียงพูดมีช่วงพีคสูงกว่าความดังเฉลี่ยมาก ถ้าเร่งอย่างเดียวจะแตก
        # จึงบีบช่วงไดนามิกเบา ๆ และกันพีคด้วย limiter ก่อน แล้วค่อยปรับความดังให้ตรงเป้า
        lufs, _ = loudness(raw)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
                        "-af", f"volume={TARGET_LUFS - lufs:.2f}dB,"
                               "acompressor=threshold=0.125:ratio=3:attack=5:release=150,"
                               f"alimiter=limit={LIMIT:.3f}:level=false,"
                               "aformat=channel_layouts=stereo",
                        str(mastered)], check=True)
        lufs, _ = loudness(mastered)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(mastered),
                        "-af", f"volume={TARGET_LUFS - lufs:.2f}dB,alimiter=limit={LIMIT:.3f}:level=false",
                        "-c:a", "aac", "-b:a", "160k", str(clean_m4a)], check=True)
    final_lufs, final_peak = loudness(clean_m4a)

    # ---- คำบรรยายและกราฟิก ----
    def src_end_of(k):
        if k + 1 < len(sel):
            nxt = cap_starts[k + 1]
            spoken = max([r[1] for r in regions if r[0] < nxt - 0.05 and r[1] > cap_starts[k]]
                         or [nxt])
            return min(nxt, spoken + 0.3)
        return src_end

    caps = []
    for k, (si, ci, text, _, _) in enumerate(sel):
        a = to_output(cap_starts[k] - 0.05, segs)
        b = to_output(src_end_of(k), segs)
        caps.append((si, text, a, max(b, a + 0.5)))
    total = voice_len + END_CARD

    ev = guide.event
    events = [
        ev(0, total, "Title", r"{\pos(540,260)}THE WALKING DEAD"),
        ev(0, voice_len, "Label", r"{\pos(540,338)}สรุปเนื้อเรื่อง · " + cfg["label"]),
    ]
    for si in wanted:
        sc = [c for c in caps if c[0] == si]
        title = sections[si]["title"]
        if title.startswith("ซีซั่น"):
            events.append(ev(sc[0][2], sc[-1][3], "Badge",
                             r"{\pos(540,450)" + POP + "}" + title))
    for k, (si, text, a, b) in enumerate(caps):
        lines = guide.wrap(text, CAPTION_WIDTH)
        events.append(ev(a, b, "Caption", r"{\pos(540,880)\blur2" + POP + "}"
                         + r"\N".join(highlight(l) for l in lines)))

    banners = []
    for key, text in cfg["banners"]:
        k = next(i for i, c in enumerate(caps) if c[1].startswith(key))
        banners.append((k, text))
    banners.sort()
    for n, (k, text) in enumerate(banners):
        si = caps[k][0]
        end_k = max(i for i, c in enumerate(caps) if c[0] == si)
        if n + 1 < len(banners) and caps[banners[n + 1][0]][0] == si:
            end = caps[banners[n + 1][0]][2]
        else:
            end = caps[end_k][3]
        events.append(ev(caps[k][2], end, "Banner", r"{\pos(540,1240)" + POP + "}" + text))

    use_broll = film is not None and "broll" in cfg
    if use_broll:
        events.append(ev(0, total, "Credit", r"{\pos(540,385)}" + FILM["credit"]))

    y = 640
    step = {"EndBig": 120, "EndText": 80, "EndGap": 90, "EndNext": 100, "EndSmall": 70}
    for i, (style, text) in enumerate(cfg["end_card"]):
        if text:
            fade = r"{\pos(540," + str(y) + r")\fad(" + str(150 + 120 * i) + ",0)}"
            events.append(ev(voice_len, total, style, fade + text))
        y += step[style]

    ass = out_dir / f"part{part_no}.ass"
    ass.write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")
    srt = out_dir / f"part{part_no}.srt"
    srt.write_text("\n".join(f"{i}\n{srt_ts(a)} --> {srt_ts(b)}\n{text}\n"
                             for i, (_, text, a, b) in enumerate(caps, 1)), encoding="utf-8")

    # ---- วิดีโอ ----
    video = out_dir / f"twd_part{part_no}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        broll_report = []
        if use_broll:
            frame = lambda t: round(t * FPS)
            starts = []
            for key, t, frac in cfg["broll"]:
                if key == "END":
                    starts.append((frame(voice_len), t, frac, True))
                else:
                    c = next(c for c in caps if c[1].startswith(key))
                    starts.append((0 if not starts else frame(c[2]), t, frac, False))
            ends = [s[0] for s in starts[1:]] + [frame(total)]
            plan = [(f0, f1, t, frac, is_end) for (f0, t, frac, is_end), f1 in zip(starts, ends)]
            base = Path(tmp) / "broll.mp4"
            broll_report = render_broll(film, plan, base, tmp)
            video_in = ["-i", str(base)]
            look = "noise=alls=6:allf=u"
        else:
            video_in = ["-f", "lavfi", "-i", f"color=c=0x0e0e0e:s=1080x1920:r={FPS}:d={total:.2f}"]
            look = "noise=alls=10:allf=u"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *video_in,
             "-i", clean_m4a.name,
             "-filter_complex", f"[0:v]{look},vignette=PI/4,ass={ass.name}[vid];"
                                f"[1:a]apad=whole_dur={total:.2f}[aud]",
             "-map", "[vid]", "-map", "[aud]", "-t", f"{total:.2f}",
             "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", video.name],
            cwd=out_dir, check=True,
        )

    print(f"{video}  {total:.1f}s (เสียงพากย์ {voice_len:.1f}s + การ์ดท้าย {END_CARD:.0f}s)")
    print(f"ความดัง {final_lufs:.1f} LUFS, true peak {final_peak:.1f} dBFS")
    print(f"ใช้ช่วงเสียงต้นฉบับ {src_start:.2f}–{src_end:.2f}s, ย่นช่วงเงียบ {len(segs) - 1} จุด, "
          f"lag {lag:+.2f}s, จับคู่จุดเริ่มพูดได้ {snapped}/{len(sel)} ท่อน")
    for k, (si, text, a, b) in enumerate(caps):
        flag = "" if picks[k] is not None else "  (ประมาณจากเวลาในวิดีโอนำพากย์)"
        print(f"  {a:6.2f}-{b:6.2f}  {text}{flag}")
    if broll_report:
        print("ภาพประกอบ (เวลาในคลิป ← วินาทีในหนัง, ความเร็ว):")
        for at, t, src, dur, speed in broll_report:
            slow = f"  slow-mo x{speed:.2f}" if speed > 1 else ""
            print(f"  {at:6.2f}s ← {src:7.2f}–{src + dur:7.2f}s (เลือกไว้ {t}){slow}")


if __name__ == "__main__":
    film = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
    build(int(sys.argv[1]), Path(sys.argv[2]).resolve(), film)
