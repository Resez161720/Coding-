# 3) สร้าง Dashboard, จอทีวี, รายงานอัตโนมัติ และแจ้งเตือน

ทำตามลำดับ ① → ② → ③ แต่ละตัวใช้เวลาประมาณ 30–60 นาที
ทุกชีตให้ต่อกับ **published data source** (ชื่อขึ้นต้นด้วย `FAC -`)

> **Shifts Ago** = 0 คือ "กะล่าสุดที่เริ่มแล้ว" (ถ้ากำลังเดินอยู่ก็คือกะนี้), 1 = กะก่อนหน้า
> ช่วงก่อนกะแรกของวันเริ่ม หรือวันหยุด ค่า 0 จะเป็นกะที่จบไปแล้วล่าสุด — ใช้คู่กับ **Is Current Shift** ถ้าต้องการเฉพาะกะที่กำลังเดิน
> ไม่ต้องห่วงเรื่องกะดึกข้ามเที่ยงคืน ระบบคำนวณให้แล้ว

---

## ① Dashboard "แผน vs จริง — กะนี้" (แก้ปัญหาผลิตไม่ทันแผน)

Data source: `FAC - Plan vs Actual Hourly`
ตัวกรองหลักทุกชีต: **Shifts Ago = 0**

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
1. Rows: `Machine Id`; Text: `แผนถึงตอนนี้`, `ผลิตได้`, `ส่วนต่าง`, `% ตามแผน`, `ต้องผลิตต่อชั่วโมง`, `ทำได้ต่อชั่วโมง`
2. Color: `สถานะแผน`; เรียง `Machine Id` ตาม `% ตามแผน` น้อยไปมาก

**รวมเป็น Dashboard:** ขนาด *Fixed 1920 × 1080* (สำหรับจอทีวี) วาง 1a ด้านบน, 1b ซ้าย, 1c ขวา
ตั้ง *Use as Filter* ที่ชีต 1c → คลิกเครื่องแล้วกราฟ 1b แสดงเฉพาะเครื่องนั้น

> แผนของชั่วโมงปัจจุบันจะถูกนับก็ต่อเมื่อมียอดของชั่วโมงนั้นส่งเข้ามาแล้ว (หรือชั่วโมงจบแล้ว)
> ถ้ายอดผลิตเข้าระบบทีละชั่วโมง ตัวเลขจะอัปเดตเป็นขั้น ๆ ทุกต้นชั่วโมง — เป็นเรื่องปกติ

---

## ② Dashboard "สาเหตุเครื่องหยุด" (หาว่าเสียเวลาไปกับอะไร)

Data source: `FAC - Downtime`
ตัวกรองหลัก: **Is Planned Stop = 0**, **Is Scheduled = 1** และ `Prod Date` → *Relative dates → Last 7 days*

**ชีต 2a — Pareto**
1. Columns: `Reason Name TH`; Rows: `นาทีหยุด` และ `Pareto % สะสม`
2. เรียง `Reason Name TH` จากมากไปน้อยตาม `นาทีหยุด`
3. `Pareto % สะสม` → *Compute Using → Reason Name TH* → *Dual Axis* (ไม่ต้อง Synchronize) → Mark = Line
4. ใส่ Reference Line คงที่ 0.8 บนแกน % (เส้น 80%)
5. ปุ่มสลับมุมมอง: สร้าง Parameter `ดูตาม` (String, รายการ: สาเหตุ / เครื่อง / กะ) + calculated field `มิติ Pareto`
   `CASE [ดูตาม] WHEN "เครื่อง" THEN [Machine Id] WHEN "กะ" THEN [Shift Code] ELSE [Reason Name TH] END`
   แล้วใช้ `มิติ Pareto` แทน `Reason Name TH` — **ต้องตั้งใหม่ 2 อย่าง**: (1) เรียง `มิติ Pareto` จากมากไปน้อยตาม `นาทีหยุด`
   (2) `Pareto % สะสม` → *Compute Using → มิติ Pareto* ไม่งั้นเส้น % สะสมจะคิดตามลำดับตัวอักษร ไม่ใช่ Pareto

**ชีต 2b — Timeline เครื่องหยุด (วันที่เลือก)**
1. Columns: `Seg Start` (Exact Date, Continuous); Rows: `Machine Id`; Mark = **Gantt Bar**
2. Size: สร้าง field `ระยะ (วัน)` = `DATEDIFF('second', [Seg Start], [Seg End]) / 86400` แล้ววางที่ Size
3. Color: `หมวดความสูญเสีย`; Tooltip: `Reason Name TH`, `Note`, `Downtime Min`

**ชีต 2c — ตัวเลข** `นาทีหยุด`, `จำนวนครั้ง`, `% ไม่ระบุสาเหตุ` (เป้า < 10%), `MTTR (นาที)`

**Dashboard:** 2c บน, 2a กลาง, 2b ล่าง — ตั้ง 2a เป็น *Use as Filter* (คลิกสาเหตุ → timeline แสดงเฉพาะสาเหตุนั้น)

---

## ③ Dashboard "แผนเกินกำลังไหม / เวลาหายไปไหน" (แก้เครื่องไหนก่อน)

**ชีต 3a — ตัวเลข** (data source `FAC - OEE by Shift`, ตัวกรอง **Is Shift Closed = 1** และ `Prod Date` → *Last 7 days*)
`OEE`, `Availability`, `Performance`, `Quality`, `Attainment %`, `Utilization`

**ชีต 3b — แผนข้างหน้าเกินกำลังไหม** (data source `FAC - Plan Capacity`) — ชีตสำคัญที่สุดสำหรับฝ่ายวางแผน
1. ตัวกรอง `Prod Date` → *Next 7 days* (รวมวันนี้)
2. Rows: `Machine Id`; Columns: `Load vs Capacity %` (แท่ง)
3. Reference Line คงที่ที่ **1** (= 100% ของกำลังที่ทำได้จริง)
4. Color: `แผนเกินกำลัง?` (แดง = แผนเกินกำลัง, เหลือง = แผนตึง, เขียว = อยู่ในกำลัง)
5. อ่านผล: แท่งยาวเกินเส้น 100% = ถ้าเครื่องทำงานได้เท่าที่ผ่านมา จะผลิตไม่ทันแผน **ต้องแก้ก่อนถึงวันผลิต**

**ชีต 3c — เวลาหายไปไหน (แท่งซ้อน)** (data source `FAC - OEE by Shift`, ตัวกรองเหมือน 3a)
1. Rows: `Machine Id`; Columns: *Measure Values*
2. ตัวกรอง *Measure Names*: `เวลาที่ได้ของดี`, `เสีย - เครื่องหยุด`, `เสีย - เดินช้า/ว่าง`, `เสีย - ของเสีย`, `หยุดตามแผน`
3. Color: เขียว = ได้ของดี, แดง = เครื่องหยุด, ส้ม = เดินช้า/ว่าง, ม่วง = ของเสีย, เทา = หยุดตามแผน
4. เรียงตาม `Attainment %` น้อยไปมาก (เครื่องที่ไม่ทันแผนอยู่บนสุด)

**ชีต 3d — Heatmap OEE รายวัน**
Rows: `Machine Id`; Columns: `Prod Date` (วัน); Mark = Square; Color: `OEE`; Label: `OEE`

**Dashboard:** 3a บน, 3b + 3c กลาง, 3d ล่าง

**วิธีหาว่าทำไมผลิตไม่ทันแผน:**
1. ชีต 3b แดง → **แผนเกินกำลังเครื่อง** → ฝ่ายวางแผนย้ายงาน/เพิ่ม OT หรือต้องเพิ่ม OEE ของเครื่องนั้น
2. ชีต 3c ของเครื่องที่ Attainment ต่ำ ดูว่าก้อนไหนใหญ่สุด
   - *เครื่องหยุด* (แดง) → ไปดู Pareto ใน ② ว่าสาเหตุอะไร
   - *เดินช้า/ว่าง* (ส้ม) → เครื่องเดินช้ากว่ามาตรฐาน หรือมีเวลาว่างที่ไม่ได้บันทึก
   - *ของเสีย* (ม่วง) → ปัญหาคุณภาพ
   - *หยุดตามแผน* (เทา) → PM/ประชุม/ไม่มีงาน กินเวลาผลิต — ฝ่ายวางแผนต้องหักเวลานี้ออกตอนออกแผน
3. ถ้าเป็นคอขวดที่รู้อยู่แล้ว ตั้ง `is_bottleneck = 1` ใน `mfg.machine` แล้วใช้กรองดูเฉพาะคอขวดได้

---

## ④ จอทีวีหน้าไลน์

1. Publish Dashboard ① (ใช้ data source `FAC - Plan vs Actual Hourly` แบบ **Live** ถ้าอยากได้ข้อมูลสดกว่ารายชั่วโมง)
   **สำคัญ:** เจ้าของ workbook เปิด workbook ใน Tableau Cloud → ปุ่ม … → *Edit Data Freshness Policy…* → เลือก **Ensure data is fresh every 5 minutes** (หรือ *Always live*) → OK
   ถ้าไม่ตั้ง Tableau Cloud จะแสดงข้อมูลที่แคชไว้ได้นานถึง 12 ชม. แม้ data source เป็น Live — คนที่เปิดจากคอม/มือถือจะเห็นตัวเลขเก่า
2. ไลเซนส์: ใช้ **Display license** (สำหรับจอโดยเฉพาะ 1 จอ = 1 login, สิทธิ์แค่ดู) — ถามตัวแทนจำหน่ายถ้ายังไม่มี
3. ทำ Custom View แยกไลน์ (กรอง `Line Id`) → เปิด URL ของ custom view นั้นบนจอ
4. ให้หน้าจอโหลดข้อมูลใหม่เอง เลือกวิธีใดวิธีหนึ่ง
   - เพิ่ม Extension **Auto Refresh** จาก Tableau Exchange ลงใน Dashboard (เป็น Sandboxed extension รันได้เลยโดยค่าเริ่มต้น)
     แต่จอทีวีจะมีหน้าต่างถามอนุญาต extension → ให้ Site Admin ไป *Settings → Extensions* เพิ่ม URL ของ Auto Refresh ใน safe list และตั้ง **User prompts = Hide** จอจะแสดงผลเองโดยไม่ต้องกด
   - หรือใช้เบราว์เซอร์/ส่วนเสริม auto-reload ทุก 5 นาที และเติม `:refresh=yes` ท้าย URL (ถ้า URL มี `?` อยู่แล้ว เช่น `?:iid=1` ให้ต่อด้วย `&:refresh=yes` ถ้ายังไม่มี ให้ต่อด้วย `?:refresh=yes`)
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
| แผนสัปดาห์หน้าเกินกำลัง | ทุกวันจันทร์ | ฝ่ายวางแผน | ชีต 3b กรองเฉพาะ `แผนเกินกำลัง?` = "แผนเกินกำลัง" + **Don't send if view is empty** |

ข้อควรระวัง
- ตัวกรองที่คลิกเลือกเองชั่วคราว **ไม่ติดไปกับอีเมล** — ต้องบันทึกเป็น Custom View ก่อน
- เปิด PDF ฉบับแรกดูว่า **ภาษาไทยแสดงถูก**
- อีเมลถูกส่งต่อได้ อย่าใส่ข้อมูลต้นทุน/กำไรในรายงานที่ส่งอีเมล
- คนที่ subscribe ให้คนอื่นได้ ต้องเป็นเจ้าของ workbook, Project Leader หรือ Site Admin
- อีเมล subscription ใหญ่ได้ไม่เกิน 2 MB ถ้าผู้รับไม่ได้รับ ให้เปลี่ยน Format เป็น PDF อย่างเดียว
- เวลาส่ง (08:30) อิงจาก *My Account Settings → Time zone for scheduled tasks* ของคนที่ตั้ง — ต้องเป็น Bangkok (ดูไฟล์ `01` ข้อ ข.6)

---

## ⑥ แจ้งเตือน (Data-driven Alerts)

เงื่อนไข: กราฟต้องมี **แกนตัวเลขต่อเนื่อง** (กราฟแท่งธรรมดาได้, Gantt/แผนที่ไม่ได้) และคนสร้างต้องมีไลเซนส์ **Explorer ขึ้นไป** (Viewer กดรับได้อย่างเดียว)

| แจ้งเตือน | ทำชีตแบบนี้ | เงื่อนไข |
|---|---|---|
| เครื่องผลิตช้ากว่าแผน | `FAC - Plan vs Actual Hourly`, กรอง Shifts Ago = 0 และ Is Current Shift = 1, Rows: `Machine Id`, Columns: `% ตามแผน` (แท่ง) | ต่ำกว่า 0.9 |
| เครื่องหยุดนาน | `FAC - Downtime`, กรอง Is Planned Stop = 0 และ Is Current Shift = 1, Rows: `Machine Id`, Columns: `นาทีหยุด` | สูงกว่า 45 |
| ของเสียสูง | `FAC - OEE by Shift`, กรอง Shifts Ago = 1, Rows: `Machine Id`, Columns: `Scrap %` | สูงกว่า 0.03 |

ขั้นตอน: Publish ชีต → เปิดใน Tableau Cloud → **Watch → Alerts → Create** → ตั้งเงื่อนไข ความถี่ และผู้รับ → ติ๊ก *Make visible to others* ให้คนอื่นกดรับได้
แจ้งเตือนทำงานตามรอบ refresh (ประมาณทุกชั่วโมง) — **ไม่ใช่สัญญาณเตือนฉุกเฉิน**
ช่องทาง: อีเมล / กระดิ่งแจ้งเตือนในเว็บ Tableau / Slack (ถ้า Site Admin เชื่อม Tableau for Slack)
ถ้าต้องการแจ้งเตือนเข้ามือถือ ให้ตั้ง Threshold ใน Pulse metric (⑦) แล้วกด Follow ในแอป Tableau Mobile (ส่งเข้า LINE ตรง ๆ ไม่ได้ เพราะ LINE Notify ปิดบริการแล้ว)

---

## ⑦ Tableau Pulse สำหรับผู้บริหาร (มีใน Tableau Cloud ทุกรุ่น)

0. Site Admin เปิดก่อน (ค่าเริ่มต้นปิด): *Settings → Tableau Pulse → Deployment → Turn on Tableau Pulse*
   ถ้าต้องการสรุปด้วย AI: *Settings → General → AI in Tableau → Tableau Pulse* (ค่าเริ่มต้นปิดเช่นกัน)
   คนสร้าง Metric Definition ต้องเป็น Creator / Explorer (can publish) / Site Admin Explorer
1. Tableau Cloud → **Pulse** → *New Metric Definition* → เลือก data source `FAC - OEE by Shift`
2. ตัวชี้วัด
   - `Good QTY`, `Unplanned Downtime Min`: เลือกที่ Measure + Aggregation = Sum ได้เลย
   - `OEE`, `Attainment %` เป็นสัดส่วน (SUM ÷ SUM) → กด **Create Advanced Definition** ลากฟิลด์ `OEE` (หรือ `Attainment %`) ไปที่ Measure → Apply
     ตั้ง Number format = Percentage และให้ค่าแสดงแบบไม่สะสม (non-cumulative)
3. Time dimension: `Prod Date`; Adjustable metric filters: `Line Id`, `Machine Id`, `Shift Code`
4. Definition filters: **Is Shift Closed = 1** (ไม่งั้นกะที่ยังเดินอยู่จะทำให้ตัวเลขวันนี้ดูตก)
5. Time → **Date offset = 1 day** (วันนี้ยังไม่มีกะที่ปิดครบ ถ้าไม่ตั้ง ค่าล่าสุดจะว่าง)
6. ทิศทาง: OEE / Good QTY ขึ้น = ดี, Unplanned Downtime Min ขึ้น = ไม่ดี

ผู้บริหารกด *Follow* แล้วจะได้สรุปทางอีเมล (และ Slack/Teams ถ้าเชื่อมไว้) และแจ้งเตือน push ในแอป Tableau Mobile (รองรับภาษาไทย)

---

## ใช้ใน "ประชุมเช้า 15 นาที" (ส่วนที่ทำให้ผลิตทันแผนจริง)
1. ③ ชีต 3b: แผนวันนี้–สัปดาห์นี้ เครื่องไหนเกินกำลัง → ฝ่ายวางแผนย้ายงาน/เพิ่ม OT ก่อนถึงวันผลิต
2. ③ ชีต 3c: เมื่อวานเครื่องไหนไม่ทันแผน เสียเวลาที่ก้อนไหน
3. ② Pareto: เลือก 1–2 สาเหตุแรก → มอบหมายคนแก้ พร้อมวันเสร็จ
4. ดู `% ไม่ระบุสาเหตุ` → ถ้าเกิน 10% ต้องให้หน้างานระบุสาเหตุให้ครบก่อน ไม่งั้น Pareto ไม่น่าเชื่อถือ
5. สัปดาห์ถัดไปดู ③ ชีต 3d ว่าเครื่องที่แก้ OEE ดีขึ้นจริงไหม
