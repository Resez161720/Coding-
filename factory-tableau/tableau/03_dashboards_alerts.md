# 3) สร้าง Dashboard, จอทีวี, รายงานอัตโนมัติ และแจ้งเตือน

ทำตามลำดับ ① → ② → ③ แต่ละตัวใช้เวลาประมาณ 30–60 นาที
ทุกชีตให้ต่อกับ **published data source** (ชื่อขึ้นต้นด้วย `FAC -`)

---

## ① Dashboard "แผน vs จริง — กะนี้" (แก้ปัญหาผลิตไม่ทันแผน)

Data source: `FAC - Plan vs Actual Hourly`
ตัวกรองหลักทุกชีต: **Shifts Ago = 0** (กะที่กำลังเดิน) — ถูกต้องเสมอ แม้กะดึกจะข้ามเที่ยงคืน

**ชีต 1a — ตัวเลขใหญ่ 4 ตัว**
1. ลาก `แผนถึงตอนนี้`, `ผลิตได้`, `ส่วนต่าง`, `ต้องผลิตต่อชั่วโมง` ไปที่ *Text* (หรือทำชีตละตัว)
2. เพิ่มตัวกรอง `Line Id` (จาก v_machine) → *Show Filter*
3. ตัวอักษรขนาด 36–48 ระบายสี `ส่วนต่าง` ด้วย `สถานะแผน`

**ชีต 1b — กราฟสะสม แผน vs จริง**
1. Columns: `Hour Start` → คลิกขวาเลือก **Exact Date** แล้วเปลี่ยนเป็น *Continuous*
2. Rows: `แผนสะสม` และ `ผลิตสะสม` → คลิกขวาตัวหลัง → *Dual Axis* → *Synchronize Axis*
3. ทั้งสองตัว: *Compute Using → Hour Start*
4. Marks: แผน = เส้นประสีเทา, ผลิตได้ = เส้นทึบสีน้ำเงิน

**ชีต 1c — ตารางรายเครื่อง (เรียงจากแย่สุด)**
1. Rows: `Machine Id`; Text: `แผนถึงตอนนี้`, `ผลิตได้`, `ส่วนต่าง`, `% ตามแผน`, `ต้องผลิตต่อชั่วโมง`
2. Color: `สถานะแผน`; เรียง `Machine Id` ตาม `ส่วนต่าง` น้อยไปมาก

**รวมเป็น Dashboard:** ขนาด *Fixed 1920 × 1080* (สำหรับจอทีวี) วาง 1a ด้านบน, 1b ซ้าย, 1c ขวา
ตั้ง *Use as Filter* ที่ชีต 1c → คลิกเครื่องแล้วกราฟ 1b แสดงเฉพาะเครื่องนั้น

---

## ② Dashboard "สาเหตุเครื่องหยุด" (หาว่าเสียเวลาไปกับอะไร)

Data source: `FAC - Downtime`
ตัวกรองหลัก: **Is Planned Stop = 0** และ `Prod Date` → *Relative dates → Last 7 days*

**ชีต 2a — Pareto**
1. Columns: `Reason Name Th`; Rows: `นาทีหยุด` และ `Pareto % สะสม`
2. เรียง `Reason Name Th` จากมากไปน้อยตาม `นาทีหยุด`
3. `Pareto % สะสม` → *Compute Using → Reason Name Th* → *Dual Axis* (ไม่ต้อง Synchronize) → Mark = Line
4. ใส่ Reference Line คงที่ 0.8 บนแกน % (เส้น 80%)
5. ปุ่มสลับ: สร้าง Parameter `ดูตาม` (สาเหตุ / เครื่อง / กะ) + field
   `CASE [ดูตาม] WHEN "เครื่อง" THEN [Machine Id] WHEN "กะ" THEN [Shift Code] ELSE [Reason Name Th] END` แล้วใช้แทน `Reason Name Th`

**ชีต 2b — Timeline เครื่องหยุด (วันที่เลือก)**
1. Columns: `Seg Start` (Exact Date, Continuous); Rows: `Machine Id`; Mark = **Gantt Bar**
2. Size: สร้าง field `ระยะ (วัน)` = `[Downtime Min] / 1440` แล้ววางที่ Size
3. Color: `หมวดความสูญเสีย`; Tooltip: `Reason Name Th`, `Note`

**ชีต 2c — ตัวเลข** `นาทีหยุด`, `จำนวนครั้ง`, `% ไม่ระบุสาเหตุ` (เป้า < 10%), `MTTR (นาที)`

**Dashboard:** 2c บน, 2a กลาง, 2b ล่าง — ตั้ง 2a เป็น *Use as Filter* (คลิกสาเหตุ → timeline แสดงเฉพาะสาเหตุนั้น)

---

## ③ Dashboard "OEE และคอขวด" (แก้เครื่องไหนก่อน)

Data source: `FAC - OEE by Shift`
ตัวกรองหลัก: **Is Shift Closed = 1** (เฉพาะกะที่จบแล้ว) และ `Prod Date` → *Last 7 days* หรือ *Last 30 days*

**ชีต 3a — ตัวเลข** `OEE`, `Availability`, `Performance`, `Quality`, `Attainment %`

**ชีต 3b — แผนเกินกำลังไหม (Bullet chart)** — ชีตสำคัญที่สุดสำหรับปัญหาผลิตไม่ทันแผน
1. Rows: `Machine Id`; Columns: `OEE` (แท่ง)
2. ลาก `Plan Load %` ไปที่ *Detail* → คลิกขวาแกน → *Add Reference Line* → Scope: **Per Cell**, Value: `Plan Load %`
3. Color: `แผนเกินกำลัง?` (แดง = แผนเกินกำลังที่ทำได้จริง)
4. อ่านผล: **เส้น (แผน) ยาวกว่าแท่ง (ทำได้จริง)** = เครื่องนี้ผลิตไม่ทันแน่นอนถ้าไม่แก้

**ชีต 3c — เวลาหายไปไหน (แท่งซ้อน)**
1. Rows: `Machine Id`; Columns: *Measure Values*
2. ตัวกรอง *Measure Names*: `เวลาที่ได้ของดี`, `เสีย - เครื่องหยุด`, `เสีย - เดินช้า`, `เสีย - ของเสีย`
3. Color: *Measure Names* (เขียว = ได้ของดี, แดง = เครื่องหยุด, ส้ม = เดินช้า, ม่วง = ของเสีย)
4. เรียงตาม `เสีย - เครื่องหยุด` มากไปน้อย

**ชีต 3d — Heatmap OEE รายวัน**
Rows: `Machine Id`; Columns: `Prod Date` (วัน); Mark = Square; Color: `OEE`; Label: `OEE`

**Dashboard:** 3a บน, 3b + 3c กลาง, 3d ล่าง — ตั้ง 3b เป็น *Use as Filter*

**วิธีหาคอขวด:** เครื่องที่ (1) แผนเกินกำลังหรือ % ตามแผนต่ำสุด และ (2) ทำให้ทั้งไลน์รอ — เริ่มแก้ที่นั่น
ดูจากชีต 3c ว่าเครื่องนั้นเสียเวลาที่ *เครื่องหยุด* (→ ไปดู Pareto ใน ②) *เดินช้า* หรือ *ของเสีย*
ถ้าเป็นคอขวดที่รู้อยู่แล้ว ตั้ง `is_bottleneck = 1` ใน `mfg.machine` แล้วใช้กรองดูเฉพาะคอขวดได้

---

## ④ จอทีวีหน้าไลน์

1. Publish Dashboard ① (ใช้ data source `FAC - Plan vs Actual Hourly` แบบ **Live** ถ้าอยากได้ข้อมูลสดกว่ารายชั่วโมง)
2. ไลเซนส์: ใช้ **Display license** (สำหรับจอโดยเฉพาะ 1 จอ = 1 login, สิทธิ์แค่ดู) — ถามตัวแทนจำหน่ายถ้ายังไม่มี
3. ทำ Custom View แยกไลน์ (กรอง `Line Id`) → เปิด URL ของ custom view นั้นบนจอ
4. ให้หน้าจอโหลดข้อมูลใหม่เอง เลือกวิธีใดวิธีหนึ่ง
   - เพิ่ม Extension **Auto Refresh** จาก Tableau Exchange ลงใน Dashboard (Site Admin ต้องอนุญาต extension ก่อน)
   - หรือใช้เบราว์เซอร์/ส่วนเสริม auto-reload ทุก 5 นาที และเติม `?:refresh=yes` ท้าย URL
5. ใช้มินิพีซี/สมาร์ททีวี เปิดเบราว์เซอร์โหมดเต็มจอ (kiosk) ปิด sleep
6. **ทดสอบ 2–3 วันก่อนติดตั้งจริง** ว่า login ไม่หลุด (Tableau Cloud บังคับยืนยันตัวตนหลายขั้น/MFA และ session มีวันหมดอายุ)

---

## ⑤ รายงานอัตโนมัติ (แก้ปัญหาทำรายงานช้า)

ทำ Dashboard "สรุปเมื่อวาน" จาก ③ + ② โดยเปลี่ยนตัวกรองเป็น `Prod Date` → *Relative dates → Yesterday* แล้ว Publish

ตั้ง Subscription ใน Tableau Cloud: เปิด Dashboard → **Watch → Subscriptions**

| รายงาน | เวลา | ผู้รับ | ตั้งค่า |
|---|---|---|---|
| สรุปเมื่อวาน (PDF แนวนอน) | ทุกวัน **08:30** (หลังกะดึกจบ 08:00 และ refresh แล้ว) | ผู้จัดการ, หัวหน้าไลน์ | Format: PDF + Image |
| สรุปต่อไลน์ | ทุกวัน 08:30 | หัวหน้าไลน์นั้น ๆ | สร้าง **Custom View** ที่กรองไลน์ แล้ว subscribe ที่ custom view นั้น |
| เครื่องที่ OEE ต่ำกว่าเป้า | ทุกวัน 08:30 | ซ่อมบำรุง, ผู้จัดการ | ชีตที่กรอง `OEE < เป้า OEE` + ติ๊ก **Don't send if view is empty** (ส่งเฉพาะวันที่มีปัญหา) |

ข้อควรระวัง
- ตัวกรองที่คลิกเลือกเองชั่วคราว **ไม่ติดไปกับอีเมล** — ต้องบันทึกเป็น Custom View ก่อน
- เปิด PDF ฉบับแรกดูว่า **ภาษาไทยแสดงถูก**
- อีเมลถูกส่งต่อได้ อย่าใส่ข้อมูลต้นทุน/กำไรในรายงานที่ส่งอีเมล

---

## ⑥ แจ้งเตือน (Data-driven Alerts)

เงื่อนไข: กราฟต้องมี **แกนตัวเลขต่อเนื่อง** (กราฟแท่งธรรมดาได้, Gantt/แผนที่ไม่ได้) และคนสร้างต้องมีไลเซนส์ **Explorer ขึ้นไป** (Viewer กดรับได้อย่างเดียว)

| แจ้งเตือน | ทำชีตแบบนี้ | เงื่อนไข |
|---|---|---|
| เครื่องผลิตช้ากว่าแผน | `FAC - Plan vs Actual Hourly`, กรอง Shifts Ago = 0, Rows: `Machine Id`, Columns: `% ตามแผน` (แท่ง) | ต่ำกว่า 0.9 |
| เครื่องหยุดนาน | `FAC - Downtime`, กรอง Is Planned Stop = 0 และ Is Current Shift = 1, Rows: `Machine Id`, Columns: `นาทีหยุด` | สูงกว่า 45 |
| ของเสียสูง | `FAC - OEE by Shift`, กรอง Shifts Ago = 1, Rows: `Machine Id`, Columns: `Scrap %` | สูงกว่า 0.03 |

ขั้นตอน: Publish ชีต → เปิดใน Tableau Cloud → **Watch → Alerts → Create** → ตั้งเงื่อนไข ความถี่ และผู้รับ → ติ๊ก *Make visible to others* ให้คนอื่นกดรับได้
แจ้งเตือนทำงานตามรอบ refresh (ประมาณทุกชั่วโมง) — **ไม่ใช่สัญญาณเตือนฉุกเฉิน**
ช่องทาง: อีเมล / แจ้งเตือนใน Tableau / Tableau Mobile (ส่งเข้า LINE ตรง ๆ ไม่ได้ เพราะ LINE Notify ปิดบริการแล้ว)

---

## ⑦ Tableau Pulse สำหรับผู้บริหาร (มีใน Tableau Cloud ทุกรุ่น)

Tableau Cloud → **Pulse** → *New Metric Definition* → เลือก data source `FAC - OEE by Shift`
- ตัวชี้วัดแนะนำ: `Good Qty` (ยอดของดี), `OEE`, `Attainment %`, `Unplanned Downtime Min`
- Time dimension: `Prod Date`; ให้ Pulse วิเคราะห์ตาม `Line Id`, `Machine Id`, `Shift Code`
- ตั้งทิศทาง: OEE / ยอดผลิต ยิ่งสูงยิ่งดี, เวลาหยุด ยิ่งต่ำยิ่งดี
ผู้บริหารกด *Follow* แล้วจะได้สรุปอัตโนมัติทางอีเมล/มือถือ (รองรับภาษาไทย)

---

## ใช้ใน "ประชุมเช้า 15 นาที" (ส่วนที่ทำให้ผลิตทันแผนจริง)
1. เปิด ③ ชีต 3b: เครื่องไหนแผนเกินกำลัง → ฝ่ายวางแผนย้ายงาน/เพิ่ม OT
2. เปิด ② Pareto: เลือก 1–2 สาเหตุแรก → มอบหมายคนแก้ พร้อมวันเสร็จ
3. ดู `% ไม่ระบุสาเหตุ` → ถ้าเกิน 10% ต้องให้หน้างานระบุสาเหตุให้ครบก่อน ไม่งั้น Pareto ไม่น่าเชื่อถือ
4. สัปดาห์ถัดไปดู ③ ชีต 3d ว่าเครื่องที่แก้ OEE ดีขึ้นจริงไหม
