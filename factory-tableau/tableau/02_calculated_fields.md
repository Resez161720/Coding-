# 2) สูตร (Calculated Fields) ที่ต้องสร้างใน Tableau

สร้างใน **data source** ก่อน Publish (คลิกขวาพื้นที่ว่างในแถบ Data → *Create Calculated Field…*)
ทุก Dashboard ที่ใช้ data source นี้จะได้สูตรเดียวกันหมด

> **เรื่องชื่อคอลัมน์:** Tableau Desktop ที่ใช้ **เมนูภาษาอังกฤษ** จะแปลงชื่อคอลัมน์ให้อ่านง่าย เช่น `run_min` → **Run Min**
> และคำ 2–3 ตัวอักษรที่ไม่มีสระ (a e i o u) จะเป็นตัวพิมพ์ใหญ่ เช่น `plan_qty` → **Plan QTY**, `reason_name_th` → **Reason Name TH**
> สูตรด้านล่างเขียนตามชื่อแบบนี้ — ถ้า Tableau ใช้ **เมนูภาษาไทย** ชื่อจะไม่ถูกแปลง (ยังเป็น `run_min`) ให้เปลี่ยนเป็นภาษาอังกฤษก่อนสร้าง data source (ดูไฟล์ `01` ข้อ ค)
> ถ้าวางสูตรแล้วชื่อฟิลด์ขึ้นสีแดง ให้ลบชื่อใน `[ ]` แล้วพิมพ์ `[` เลือกจากรายการ — คอลัมน์ที่เพิ่มเข้า view ภายหลังแล้วกด Refresh จะไม่ถูกแปลงชื่อ (Rename เองได้)
>
> **คอลัมน์ 0/1** เช่น *Is Shift Closed*, *Is Current Shift*, *Is Planned Stop*, *Is Scheduled*, *Shifts Ago*
> Tableau อาจจัดเป็น Measure — คลิกขวา → **Convert to Dimension** ก่อนใช้เป็นตัวกรอง
>
> **การจัดรูปแบบ:** ฟิลด์ที่เป็น % ให้คลิกขวา → *Default Properties → Number Format → Percentage* (ทศนิยม 1 ตำแหน่ง)

---

## Data Source: `FAC - OEE by Shift` (rpt.v_oee_shift)

### OEE และองค์ประกอบ
| ชื่อฟิลด์ | สูตร |
|---|---|
| `Availability` | `SUM([Run Min]) / SUM([Planned Production Min])` |
| `Performance` | `SUM([Ideal Run Min]) / SUM([Run Min])` |
| `Quality` | `SUM([Good Ideal Min]) / SUM([Ideal Run Min])` |
| `OEE` | `SUM([Good Ideal Min]) / SUM([Planned Production Min])` |
| `Scrap %` | `SUM([Scrap QTY]) / SUM([Total QTY])` |
| `Attainment %` | `SUM([Good QTY]) / SUM([Plan QTY Elapsed])` |
| `Utilization` | `SUM([Good Ideal Min]) / SUM([Full Shift Planned Min])` |

> ห้ามใช้ AVG ของ % — สูตรด้านบนรวมเวลาก่อนแล้วค่อยหาร เวลาดูรวมหลายเครื่อง/หลายวันจะถ่วงน้ำหนักถูกต้องเอง
>
> **Attainment %** = ผลิตได้เทียบแผน "ถึงตอนนี้" (กะที่ยังเดินอยู่จะไม่ขึ้นว่าต่ำผิด ๆ)
> **Utilization** = ใช้เวลากะไปผลิตของดีได้กี่ % รวมเวลาหยุดตามแผนด้วย — ถ้า OEE ดีแต่ Utilization ต่ำ แปลว่าเสียเวลาไปกับ PM/ประชุม/ไม่มีงาน

### เวลาหายไปไหน (นาที) — ใช้ทำกราฟแท่งซ้อน
| ชื่อฟิลด์ | สูตร |
|---|---|
| `หยุดตามแผน` | `SUM([Planned Stop Min])` |
| `เสีย - เครื่องหยุด` | `SUM([Unplanned Downtime Min])` |
| `เสีย - เดินช้า/ว่าง` | `SUM([Run Min]) - SUM([Ideal Run Min])` |
| `เสีย - ของเสีย` | `SUM([Ideal Run Min]) - SUM([Good Ideal Min])` |
| `เวลาที่ได้ของดี` | `SUM([Good Ideal Min])` |

- 4 ตัวหลัง รวมกันเท่ากับ `SUM([Planned Production Min])` พอดี และทั้ง 5 ตัวรวมกันเท่ากับ `SUM([Shift Planned Min])`
- **หยุดตามแผน ไม่ลด OEE แต่ทำให้ผลิตไม่ทันแผนได้** จึงต้องแสดงให้เห็นด้วย (สีเทา)
- **เดินช้า/ว่าง** รวมทั้งเครื่องเดินช้ากว่ามาตรฐาน และเวลาที่เครื่องว่างแต่ไม่ได้บันทึก (เช่น ผลิตครบแผนแล้วไม่มีงาน) — ถ้าก้อนนี้ใหญ่ผิดปกติ ให้ตรวจว่าหน้างานบันทึก `NO-ORDER` หรือยัง
- **หยุดเล็กน้อย** ที่บันทึกเป็นเหตุการณ์ (รหัส MINOR) นับอยู่ใน *เครื่องหยุด* ส่วนที่ไม่ได้บันทึกจะไปอยู่ใน *เดินช้า/ว่าง*

### ซ่อมบำรุง และคุณภาพข้อมูล
| ชื่อฟิลด์ | สูตร |
|---|---|
| `MTBF (ชม.)` | `SUM([Run Min]) / 60 / SUM([Breakdown Count])` |
| `% หยุดไม่ระบุสาเหตุ` | `SUM([Uncoded Downtime Min]) / SUM([Unplanned Downtime Min])` |
| `ตรวจรอบเวลามาตรฐาน` | `IF [Performance] > 1.05 THEN "Performance เกิน 100% - ตรวจรอบเวลามาตรฐาน" END` |

(MTTR ใช้จาก data source `FAC - Downtime` ซึ่งนับเวลาซ่อมตามนาฬิกา)

### เป้าหมายและสี
1. สร้าง **Parameter** ชื่อ `เป้า OEE` แบบ Float ค่าเริ่มต้น `0.75` (คลิกขวา → *Show Parameter* ถ้าอยากให้ปรับได้)
2. Calculated field:

| ชื่อฟิลด์ | สูตร |
|---|---|
| `สถานะ OEE` | `IF [OEE] >= [เป้า OEE] THEN "ถึงเป้า" ELSEIF [OEE] >= [เป้า OEE] - 0.10 THEN "ใกล้เป้า" ELSE "ต่ำกว่าเป้า" END` |

ตั้งสี: ถึงเป้า = เขียว, ใกล้เป้า = เหลือง, ต่ำกว่าเป้า = แดง

---

## Data Source: `FAC - Plan Capacity` (rpt.v_plan_capacity) — แผนข้างหน้าเกินกำลังไหม

view นี้มีเฉพาะ **กะที่กำลังเดินและกะข้างหน้าที่มีแผนแล้ว** เทียบกับ OEE จริงของเครื่องย้อนหลัง 28 วัน

| ชื่อฟิลด์ | สูตร |
|---|---|
| `แผนต้องใช้ (นาที)` | `SUM([Plan Ideal Min])` |
| `กำลังผลิตจริง (นาที)` | `SUM([Capacity Good Ideal Min])` |
| `Load vs Capacity %` | `SUM([Plan Ideal Min]) / SUM([Capacity Good Ideal Min])` |
| `แผนเกินกำลัง?` | ดูด้านล่าง |

```
IF SUM([Capacity Good Ideal Min]) = 0 OR ISNULL(SUM([Capacity Good Ideal Min])) THEN "ไม่มีข้อมูลย้อนหลัง"
ELSEIF [Load vs Capacity %] > 1.05 THEN "แผนเกินกำลัง"
ELSEIF [Load vs Capacity %] > 0.95 THEN "แผนตึง"
ELSE "แผนอยู่ในกำลัง"
END
```

วิธีอ่าน: **Load vs Capacity % เกิน 100%** = ถ้าเครื่องทำงานได้เท่าที่ผ่านมา (OEE เท่าเดิม) จะผลิตไม่ทันแผนแน่นอน
→ ฝ่ายวางแผนย้ายงานไปเครื่องอื่น/เพิ่ม OT **หรือ** ต้องเพิ่ม OEE ของเครื่องนี้ (ดูว่าเสียเวลาที่ไหนในกราฟ "เวลาหายไปไหน")
ถ้า `Plan QTY Missing CT` มากกว่า 0 แปลว่ามีสินค้าในแผนที่ยังไม่มีรอบเวลามาตรฐาน — ตัวเลขจะต่ำกว่าจริง

---

## Data Source: `FAC - Plan vs Actual Hourly` (rpt.v_plan_vs_actual_hour)

| ชื่อฟิลด์ | สูตร | ความหมาย |
|---|---|---|
| `แผนทั้งกะ` | `SUM([Plan QTY])` | แผนรวมของกะ |
| `แผนถึงตอนนี้` | `SUM([Plan QTY Elapsed])` | ควรผลิตได้เท่าไรแล้ว (นับเฉพาะชั่วโมงที่จบแล้ว/มียอดส่งเข้ามาแล้ว) |
| `ผลิตได้` | `SUM([Actual Good QTY])` | ของดีที่ผลิตได้จริง |
| `ส่วนต่าง` | `[ผลิตได้] - [แผนถึงตอนนี้]` | ติดลบ = ช้ากว่าแผน |
| `% ตามแผน` | `[ผลิตได้] / [แผนถึงตอนนี้]` | |
| `จำนวนเครื่อง` | `COUNTD([Machine Id])` | |
| `ชั่วโมงที่เหลือ` | `SUM([Remaining Planned Min]) / [จำนวนเครื่อง] / 60` | ชั่วโมงที่เหลือในกะ (หักเวลาพักแล้ว) |
| `ต้องผลิตต่อชั่วโมง` | `IF [ชั่วโมงที่เหลือ] > 0 THEN ([แผนทั้งกะ] - [ผลิตได้]) / [ชั่วโมงที่เหลือ] END` | ต้องผลิตชั่วโมงละเท่าไรถึงจะทันจบกะ |
| `ทำได้ต่อชั่วโมง` | `[ผลิตได้] / (SUM([Reported Planned Min]) / [จำนวนเครื่อง] / 60)` | อัตราที่ทำได้จริงในกะนี้ |
| `แผนสะสม` | `RUNNING_SUM(SUM([Plan QTY]))` | Table calculation |
| `ผลิตสะสม` | `IF COUNT([Actual Good QTY]) > 0 THEN RUNNING_SUM(SUM([Actual Good QTY])) END` | เส้นหยุดที่ชั่วโมงปัจจุบัน |
| `ส่วนต่างสะสม` | `[ผลิตสะสม] - [แผนสะสม]` | |
| `สถานะแผน` | `IF [ส่วนต่าง] >= 0 THEN "ตามแผน" ELSEIF [% ตามแผน] >= 0.95 THEN "ช้าเล็กน้อย" ELSE "ไม่ทันแผน" END` | ใช้ระบายสี |

- `แผนสะสม`, `ผลิตสะสม`, `ส่วนต่างสะสม` เป็น Table Calculation: หลังวางลงกราฟ คลิกขวา → *Compute Using* → **Hour Start**
- `ชั่วโมงที่เหลือ`, `ต้องผลิตต่อชั่วโมง`, `ทำได้ต่อชั่วโมง` ใช้ได้ทั้งระดับเครื่องและระดับไลน์ (หารด้วยจำนวนเครื่องให้แล้ว)
  แต่ระดับไลน์เป็นการ **บวกจำนวนชิ้นของสินค้าต่างชนิดกัน** ถ้าสินค้าต่างกันมาก ให้ดู `% ตามแผน` แทนจำนวนชิ้น

---

## Data Source: `FAC - Downtime` (rpt.v_downtime_segment)

ตัวกรองหลักของ Pareto ความสูญเสีย: **Is Planned Stop = 0** และ **Is Scheduled = 1** (ให้ตัวเลขตรงกับ Dashboard OEE)

| ชื่อฟิลด์ | สูตร |
|---|---|
| `นาทีหยุด` | `SUM([Downtime Min])` |
| `จำนวนครั้ง` | `SUM([Stop Count])` |
| `Pareto % สะสม` | `RUNNING_SUM(SUM([Downtime Min])) / TOTAL(SUM([Downtime Min]))` |
| `% ไม่ระบุสาเหตุ` | `SUM(IF [Loss Category] = "UNCODED" THEN [Downtime Min] END) / SUM([Downtime Min])` |
| `MTTR (นาที)` | `SUM(IF [Loss Category] = "BREAKDOWN" AND [Stop Count] = 1 THEN [Event Total Min] END) / SUM(IF [Loss Category] = "BREAKDOWN" THEN [Stop Count] END)` |
| `เฉลี่ยต่อครั้ง (นาที)` | `[นาทีหยุด] / [จำนวนครั้ง]` |

- **จำนวนครั้ง** ใช้ `Stop Count` (ไม่ใช้ COUNTD ของ Event Id) — การหยุดที่คร่อมกะนับครั้งเดียว และการหยุดที่อยู่ในเวลาพักทั้งหมดไม่นับ
- **MTTR** นับเวลาซ่อมตามนาฬิกา (รวมช่วงเวลาพัก) ส่วน `นาทีหยุด` หักเวลาพักออกแล้ว (ใช้คิดความสูญเสีย)

หมวดความสูญเสียภาษาไทย (สร้างเป็น Dimension ชื่อ `หมวดความสูญเสีย`):
```
CASE [Loss Category]
    WHEN "BREAKDOWN"  THEN "เครื่องเสีย"
    WHEN "SETUP"      THEN "เปลี่ยนรุ่น/ตั้งเครื่อง"
    WHEN "MINOR_STOP" THEN "หยุดเล็กน้อย"
    WHEN "MATERIAL"   THEN "วัตถุดิบ"
    WHEN "MANPOWER"   THEN "คน"
    WHEN "QUALITY"    THEN "คุณภาพ"
    WHEN "PLANNED"    THEN "หยุดตามแผน"
    WHEN "UNCODED"    THEN "ยังไม่ระบุสาเหตุ"
    ELSE "อื่น ๆ"
END
```

กลุ่มความยาวการหยุด (Dimension ชื่อ `กลุ่มความยาวการหยุด`):
```
IF [Event Total Min] < 5 THEN "1) สั้นกว่า 5 นาที"
ELSEIF [Event Total Min] < 30 THEN "2) 5-30 นาที"
ELSEIF [Event Total Min] < 120 THEN "3) 30-120 นาที"
ELSE "4) เกิน 2 ชม."
END
```

> ทบทวนรายสัปดาห์: ทำ Pareto อีกชุดที่กรอง **Is Planned Stop = 1** เพื่อดูว่าหยุดตามแผน (PM/ประชุม/ไม่มีงาน) กินเวลาเท่าไร

---

## (เสริม) Data Source: `FAC - Plan vs Actual SKU` (rpt.v_plan_vs_actual_sku)

| ชื่อฟิลด์ | สูตร |
|---|---|
| `Schedule Adherence %` | `SUM(IF [Shift Status] = "CLOSED" THEN [Adherence QTY] END) / SUM(IF [Shift Status] = "CLOSED" THEN [Plan QTY] END)` |

**Schedule Adherence** เข้มกว่า Attainment: ผลิตสินค้า A เกินแผน ไม่ช่วยชดเชยสินค้า B ที่ขาด — เหมาะดูว่า "ผลิตตรงตามที่ลูกค้าต้องการ" หรือไม่
