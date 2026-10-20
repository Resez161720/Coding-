# 2) สูตร (Calculated Fields) ที่ต้องสร้างใน Tableau

สร้างใน **data source** ก่อน Publish (คลิกขวาพื้นที่ว่างในแถบ Data → *Create Calculated Field…*)
ทุก Dashboard ที่ใช้ data source นี้จะได้สูตรเดียวกันหมด

> **เรื่องชื่อคอลัมน์:** Tableau มักแปลงชื่อคอลัมน์จาก SQL ให้อ่านง่าย เช่น `run_min` → **Run Min**
> สูตรด้านล่างเขียนตามชื่อที่แปลงแล้ว ถ้าใน Tableau ของคุณยังแสดงเป็น `run_min` ให้พิมพ์ `[` แล้วเลือกชื่อจากรายการแทน
>
> **คอลัมน์ 0/1** เช่น *Is Shift Closed*, *Is Current Shift*, *Is Planned Stop*, *Shifts Ago*
> Tableau อาจจัดเป็น Measure — คลิกขวา → **Convert to Dimension** ก่อนใช้เป็นตัวกรอง
>
> **การจัดรูปแบบ:** ฟิลด์ที่ลงท้ายด้วย % ให้คลิกขวา → *Default Properties → Number Format → Percentage* (ทศนิยม 1 ตำแหน่ง)

---

## Data Source: `FAC - OEE by Shift` (rpt.v_oee_shift)

### OEE และองค์ประกอบ
| ชื่อฟิลด์ | สูตร |
|---|---|
| `Availability` | `SUM([Run Min]) / SUM([Planned Production Min])` |
| `Performance` | `SUM([Ideal Run Min]) / SUM([Run Min])` |
| `Quality` | `SUM([Good Ideal Min]) / SUM([Ideal Run Min])` |
| `OEE` | `SUM([Good Ideal Min]) / SUM([Planned Production Min])` |
| `Scrap %` | `SUM([Scrap Qty]) / SUM([Total Qty])` |

> ห้ามใช้ AVG ของ % — สูตรด้านบนรวมเวลาก่อนแล้วค่อยหาร เวลาดูรวมหลายเครื่อง/หลายวันจะถ่วงน้ำหนักถูกต้องเอง

### แผน และ "แผนเกินกำลังหรือไม่"
| ชื่อฟิลด์ | สูตร |
|---|---|
| `Attainment %` | `SUM([Good Qty]) / SUM([Plan Qty])` |
| `Plan Load %` | `SUM([Plan Ideal Min]) / SUM([Full Shift Planned Min])` |
| `แผนเกินกำลัง?` | `IF [Plan Load %] > [OEE] THEN "แผนเกินกำลังที่ทำได้จริง" ELSE "แผนอยู่ในกำลัง" END` |

วิธีอ่าน: **Plan Load %** = แผนต้องใช้เวลาเครื่องกี่ % ถ้าเดินเร็วตามมาตรฐานไม่มีหยุดไม่มีเสีย
ถ้า **Plan Load % สูงกว่า OEE ที่ทำได้จริง** → ต่อให้ทำงานดีเท่าเดิม ก็ผลิตไม่ทันแผน ต้องแก้ที่แผน (ย้ายงาน/เพิ่ม OT) หรือเพิ่ม OEE

### เวลาที่สูญเสีย (นาที) — ใช้ทำกราฟแท่งซ้อน
| ชื่อฟิลด์ | สูตร |
|---|---|
| `เสีย - เครื่องหยุด` | `SUM([Unplanned Downtime Min])` |
| `เสีย - เดินช้า` | `SUM([Run Min]) - SUM([Ideal Run Min])` |
| `เสีย - ของเสีย` | `SUM([Ideal Run Min]) - SUM([Good Ideal Min])` |
| `เวลาที่ได้ของดี` | `SUM([Good Ideal Min])` |

4 ตัวนี้รวมกันเท่ากับ `SUM([Planned Production Min])` พอดี

### ซ่อมบำรุง และคุณภาพข้อมูล
| ชื่อฟิลด์ | สูตร |
|---|---|
| `MTTR (นาที)` | `SUM([Breakdown Min]) / SUM([Breakdown Count])` |
| `MTBF (ชม.)` | `SUM([Run Min]) / 60 / SUM([Breakdown Count])` |
| `% หยุดไม่ระบุสาเหตุ` | `SUM([Uncoded Downtime Min]) / SUM([Unplanned Downtime Min])` |
| `ตรวจรอบเวลามาตรฐาน` | `IF [Performance] > 1.05 THEN "Performance เกิน 100% - ตรวจรอบเวลามาตรฐาน" END` |

### เป้าหมายและสี
1. สร้าง **Parameter** ชื่อ `เป้า OEE` แบบ Float ค่าเริ่มต้น `0.75` (คลิกขวา → *Show Parameter* ถ้าอยากให้ปรับได้)
2. Calculated field:

| ชื่อฟิลด์ | สูตร |
|---|---|
| `สถานะ OEE` | `IF [OEE] >= [เป้า OEE] THEN "ถึงเป้า" ELSEIF [OEE] >= [เป้า OEE] - 0.10 THEN "ใกล้เป้า" ELSE "ต่ำกว่าเป้า" END` |

ตั้งสี: ถึงเป้า = เขียว, ใกล้เป้า = เหลือง, ต่ำกว่าเป้า = แดง

---

## Data Source: `FAC - Plan vs Actual Hourly` (rpt.v_plan_vs_actual_hour)

| ชื่อฟิลด์ | สูตร | ความหมาย |
|---|---|---|
| `แผนทั้งกะ` | `SUM([Plan Qty])` | แผนรวมของกะ |
| `แผนถึงตอนนี้` | `SUM([Plan Qty Elapsed])` | ควรผลิตได้เท่าไรแล้ว ณ ตอนนี้ |
| `ผลิตได้` | `SUM([Actual Good Qty])` | ของดีที่ผลิตได้จริง |
| `ส่วนต่าง` | `[ผลิตได้] - [แผนถึงตอนนี้]` | ติดลบ = ช้ากว่าแผน |
| `% ตามแผน` | `[ผลิตได้] / [แผนถึงตอนนี้]` | |
| `ชั่วโมงที่เหลือ` | `SUM([Remaining Planned Min]) / 60` | หักเวลาพักแล้ว |
| `ต้องผลิตต่อชั่วโมง` | `IF [ชั่วโมงที่เหลือ] > 0 THEN ([แผนทั้งกะ] - [ผลิตได้]) / [ชั่วโมงที่เหลือ] END` | ต้องเร่งเท่าไรถึงจะทันจบกะ |
| `ทำได้ต่อชั่วโมง` | `[ผลิตได้] / ((SUM([Slot Planned Min]) - SUM([Remaining Planned Min])) / 60)` | อัตราที่ทำได้จริงในกะนี้ |
| `แผนสะสม` | `RUNNING_SUM(SUM([Plan Qty]))` | Table calculation |
| `ผลิตสะสม` | `IF COUNT([Actual Good Qty]) > 0 THEN RUNNING_SUM(SUM([Actual Good Qty])) END` | เส้นหยุดที่ชั่วโมงปัจจุบัน |
| `ส่วนต่างสะสม` | `[ผลิตสะสม] - [แผนสะสม]` | |
| `สถานะแผน` | `IF [ส่วนต่าง] >= 0 THEN "ตามแผน" ELSEIF [% ตามแผน] >= 0.95 THEN "ช้าเล็กน้อย" ELSE "ไม่ทันแผน" END` | ใช้ระบายสี |

`แผนสะสม`, `ผลิตสะสม`, `ส่วนต่างสะสม` เป็น Table Calculation: หลังวางลงกราฟ คลิกขวา → *Compute Using* → **Hour Start** (หรือ Slot No)

---

## Data Source: `FAC - Downtime` (rpt.v_downtime_segment)

| ชื่อฟิลด์ | สูตร |
|---|---|
| `นาทีหยุด` | `SUM([Downtime Min])` |
| `จำนวนครั้ง` | `COUNTD([Event Id])` |
| `Pareto % สะสม` | `RUNNING_SUM(SUM([Downtime Min])) / TOTAL(SUM([Downtime Min]))` |
| `% ไม่ระบุสาเหตุ` | `SUM(IF [Loss Category] = "UNCODED" THEN [Downtime Min] END) / SUM([Downtime Min])` |
| `MTTR (นาที)` | `SUM(IF [Loss Category] = "BREAKDOWN" THEN [Downtime Min] END) / COUNTD(IF [Loss Category] = "BREAKDOWN" THEN [Event Id] END)` |
| `เฉลี่ยต่อครั้ง (นาที)` | `[นาทีหยุด] / [จำนวนครั้ง]` |

หมวดความสูญเสียภาษาไทย (สร้างเป็น Dimension):
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
ตั้งชื่อว่า `หมวดความสูญเสีย`

กลุ่มความยาวการหยุด (Dimension):
```
IF [Event Total Min] < 5 THEN "1) สั้นกว่า 5 นาที"
ELSEIF [Event Total Min] < 30 THEN "2) 5-30 นาที"
ELSEIF [Event Total Min] < 120 THEN "3) 30-120 นาที"
ELSE "4) เกิน 2 ชม."
END
```
ตั้งชื่อว่า `กลุ่มความยาวการหยุด`

> Pareto ความสูญเสีย ให้ใส่ตัวกรอง **Is Planned Stop = 0** เสมอ (ตัดการหยุดตามแผนออก)
