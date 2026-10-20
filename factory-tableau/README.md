# ชุดเริ่มต้น SQL Server + Tableau Cloud สำหรับโรงงาน

เป้าหมาย: แก้ 2 ปัญหาหลัก — **ผลิตไม่ทันแผน** และ **ทำรายงานช้า**
โดยให้ข้อมูลไหลจาก SQL Server ในโรงงาน → Tableau Bridge → Tableau Cloud แล้วส่งรายงาน/แจ้งเตือนอัตโนมัติ

```
เครื่องจักร / ฟอร์ม Excel / ระบบเดิม
        │  (07 นำเข้าจาก Excel, 06 ดึงจากระบบเดิม, หรือ PLC เรียก procedure)
        ▼
SQL Server ในโรงงาน
  schema mfg  = ตารางเก็บข้อมูล
  schema rpt  = view ที่คำนวณเสร็จแล้ว ให้ Tableau อ่าน
        │  (login tableau_reader อ่านอย่างเดียว)
        ▼
Tableau Bridge (เครื่อง Windows ในโรงงาน)
        ▼
Tableau Cloud → Dashboard / อีเมลรายงาน / แจ้งเตือน / จอทีวี
```

## ไฟล์ในชุดนี้

| ไฟล์ | ทำอะไร |
|---|---|
| `sql/00_create_databases.sql` | สร้างฐานข้อมูล `FactoryBI` (ของจริง) และ `FactoryBI_Demo` (ทดลอง) |
| `sql/01_schema.sql` | สร้างตาราง: เครื่องจักร, สินค้า, รอบเวลามาตรฐาน, กะ, แผน, ยอดผลิต, เครื่องหยุด |
| `sql/02_views_and_procs.sql` | สร้าง view สำหรับ Tableau (OEE, แผน vs จริง, แผนเกินกำลัง, Pareto) และ procedure บันทึกข้อมูล |
| `sql/03_reference_data.sql` | ใส่กะ/เวลาพัก/รหัสสาเหตุหยุด และสร้างปฏิทินกะ — **แก้ให้ตรงโรงงานก่อนรัน** |
| `sql/04_sample_data.sql` | ข้อมูลตัวอย่าง 30 เครื่อง 28 วัน (ใช้กับ `FactoryBI_Demo` เท่านั้น) |
| `sql/05_tableau_login.sql` | สร้างผู้ใช้ `tableau_reader` อ่านได้เฉพาะ view |
| `sql/06_load_from_existing_TEMPLATE.sql` | แม่แบบดึงข้อมูลอัตโนมัติจากตารางเดิมของโรงงาน (ถ้ามี PLC/MES/โปรแกรมเดิม) |
| `sql/07_excel_import.sql` | นำเข้าจาก Excel: เครื่องจักร/รอบเวลา, แผนการผลิต, ยอดผลิต, เครื่องหยุด |
| `tableau/01_connect_bridge_publish.md` | ตั้ง SQL Server, Tableau Bridge, เชื่อมต่อและ Publish |
| `tableau/02_calculated_fields.md` | สูตรทั้งหมดที่ต้องสร้างใน Tableau (copy ไปวางได้เลย) |
| `tableau/03_dashboards_alerts.md` | ขั้นตอนสร้าง Dashboard 3 ตัว + จอทีวี + รายงานอัตโนมัติ + แจ้งเตือน |

ต้องใช้ **SQL Server 2016 SP1 ขึ้นไป** (รุ่น Express ก็ใช้ได้)

---

## เริ่มต้น: ลองกับข้อมูลตัวอย่างก่อน (ประมาณ 15 นาที)

**ต่อ SSMS ครั้งแรก** (หน้าต่าง *Connect to Server*):
- Server name: `ชื่อเครื่อง\SQLEXPRESS` (ถ้าเปิด SSMS บนเครื่อง SQL Server เองใส่ `.\SQLEXPRESS`; รุ่น Standard ที่ติดตั้งแบบปกติใส่แค่ชื่อเครื่อง)
- Authentication: **Windows Authentication** (บัญชีที่ติดตั้ง SQL Server หรือเป็นผู้ดูแล SQL Server)
- SSMS รุ่น 20 ขึ้นไป: ติ๊ก **Trust server certificate** ไม่งั้นจะขึ้น "The certificate chain was issued by an authority that is not trusted"

แล้วทำตามลำดับ (ทุกไฟล์: File → Open → เลือกไฟล์ → เลือกฐานข้อมูลที่ช่อง *Available Databases* บนแถบเครื่องมือ → กด **Execute**)

1. `00_create_databases.sql` (ฐานข้อมูลอะไรก็ได้ เช่น master)
2. เลือก **FactoryBI_Demo** แล้วรัน `01_schema.sql` → `02_views_and_procs.sql` → `03_reference_data.sql` → `04_sample_data.sql`
3. แก้รหัสผ่านใน `05_tableau_login.sql` แล้วรันใน **FactoryBI_Demo**
4. ลองดูผล:
   ```sql
   SELECT TOP 20 * FROM rpt.v_oee_shift ORDER BY shift_start DESC;
   SELECT * FROM rpt.v_plan_vs_actual_hour WHERE shifts_ago = 0 AND machine_id = N'CNC-03' ORDER BY slot_no;
   SELECT * FROM rpt.v_plan_capacity ORDER BY machine_id, shift_start;
   ```
5. ไปต่อที่ `tableau/01_connect_bridge_publish.md` แล้วสร้าง Dashboard จากข้อมูลตัวอย่าง (ช่อง Database ใส่ `FactoryBI_Demo`)

ข้อมูลตัวอย่างจำลองสถานการณ์ไว้ให้หาเจอใน Dashboard:
- **CNC-03 และ PRS-02 ได้แผนเกือบเต็มเวลาเครื่อง (97%)** จึงเกินกำลังที่ทำได้จริง — CNC-03 เกินมากที่สุด (ราว 135% ในชีต 3b) เพราะ **เสียบ่อย (คอขวด)**, PRS-02 ราว 125%
- **PRS-05 เดินช้า** (Performance ราว 70% แผนจึงเกินกำลังราว 110%)
- **INJ-04 ของเสียสูง**

> ข้อมูลตัวอย่างสร้างถึง **เวลาที่รัน 04** เท่านั้น (แผนล่วงหน้า 2 วัน) — วันต่อ ๆ ไป OEE จะลดลงจนเป็น 0 และจอ ① / ชีต 3b จะว่าง
> **ไม่ใช่ Dashboard พัง** ถ้าทำ Dashboard ต่อวันอื่น ให้สร้าง Demo ใหม่ (ไม่ถึง 1 นาที) แล้วกด Refresh extract ใน Tableau
>
> เริ่ม Demo ใหม่: SSMS คลิกขวา `FactoryBI_Demo` → Delete → ติ๊ก **Close existing connections** → OK แล้วรันข้อ 1–3 ใหม่

---

## ใช้กับข้อมูลจริง

1. แก้ `03_reference_data.sql` ให้ตรงกับโรงงาน
   - **รูปแบบกะ**: แก้ `@pattern` (`'2x12'`, `'3x8'` หรือ `'3x8_next'`) และเวลาเริ่ม/เวลาพักในตารางของรูปแบบนั้น
   - **วันทำงาน**: `@work_saturday`, `@work_sunday` และวันหยุดโรงงานในตาราง `mfg.holiday`
   - **รหัสสาเหตุหยุด**: ไม่ควรเกิน ~20 รหัส ให้ฝ่ายผลิต/ซ่อมบำรุง/QC ตกลงร่วมกัน
2. เลือกฐานข้อมูล **FactoryBI** แล้วรัน `01` → `02` → `03` → `07` → `05` (**ไม่ต้องรัน 04**)
3. ใส่ข้อมูลหลักจาก Excel ด้วย `mfg.usp_import_master` (วิธีอยู่หัวไฟล์ `07`) — **ทำครั้งแรก และทุกครั้งที่มีเครื่องหรือสินค้าใหม่ก่อนเริ่มผลิต**
   - เครื่องจักรทั้ง 30 ตัว (`is_active = 0` สำหรับเครื่องที่ไม่ได้ใช้)
   - **รอบเวลามาตรฐานต่อสินค้า x เครื่อง** ใช้ค่าที่เร็วที่สุดที่ทำได้จริงอย่างสม่ำเสมอ ไม่ใช่ค่าจากแคตตาล็อก
     เครื่องที่ 1 รอบได้หลายชิ้น (หลายคาวิตี้) ใส่ `cycle_sec` = วินาทีต่อรอบ และ `pcs_per_cycle` = ชิ้นต่อรอบ เช่น 30 วินาที 4 คาวิตี้ = 7.5 วินาที/ชิ้น
4. ให้ข้อมูลประจำวันไหลเข้า เลือกวิธีที่เหมาะ
   | ข้อมูล | มีระบบเดิมเก็บใน SQL อยู่แล้ว | มี PLC / Gateway | ยังไม่มีอะไรเลย |
   |---|---|---|---|
   | ยอดผลิตรายชั่วโมง | `06` (ดึงอัตโนมัติ) | เรียก `mfg.usp_upsert_production_hour` | ฟอร์ม Excel กรอกทุก 1–2 ชม. → `mfg.usp_import_production` (`07`) |
   | เครื่องหยุด | `06` (ดึงอัตโนมัติ) | `mfg.usp_downtime_start` / `usp_downtime_stop` | ฟอร์ม Excel → `mfg.usp_import_stops` (`07`) |
   | ระบุสาเหตุที่ยังว่าง | — | `mfg.usp_downtime_set_reason` | `mfg.usp_downtime_set_reason` หรือนำเข้าซ้ำด้วย `usp_import_stops` |
   | ของเสียที่ QC พบภายหลัง | `mfg.usp_add_scrap` | `mfg.usp_add_scrap` | `mfg.usp_add_scrap` |
   | แผนการผลิต | — | — | ฟอร์ม Excel → `mfg.usp_import_plan` (`07`) — **ไฟล์ต้องมีแผนครบทุกเครื่องของวัน/กะนั้น** เพราะแผนเดิมที่ไม่อยู่ในไฟล์จะถูกลบ |

   ของเสียที่บันทึกด้วย `usp_add_scrap` ระบบจำแยกไว้ การส่งยอดซ้ำหรือดึงข้อมูลซ้ำจะไม่ลบทิ้ง
5. ตรวจคุณภาพข้อมูลทุกเช้า — ดูหัวข้อ "งานประจำ" ด้านล่าง

### กติกาสำคัญของข้อมูล
- เวลาทั้งหมดเก็บเป็น **เวลาไทย** (ไม่ใช่ UTC)
- **กะดึกที่ข้ามเที่ยงคืน** ปกตินับเป็นวันผลิตของวันที่เริ่มกะ (เช่น กะดึกคืนวันที่ 20 ที่จบ 08:00 วันที่ 21 = วันผลิต 20)
  ยกเว้นเลือก `@pattern = '3x8_next'` (กะ 23:00 นับเป็นกะแรกของวันถัดไป) — แผนใน Excel ต้องใช้วันผลิตตามนี้
- **เวลาพัก** ถูกหักออกให้อัตโนมัติ ไม่ต้องบันทึกเป็นเครื่องหยุด
- **เปลี่ยนรุ่น/ตั้งเครื่อง** นับเป็นความสูญเสีย (ตามมาตรฐาน OEE) ไม่ใช่หยุดตามแผน
- **หยุดเล็กน้อย** ที่บันทึกเป็นเหตุการณ์ (รหัส MINOR) นับใน Availability (ตำราบางเล่มนับใน Performance — ค่า OEE รวมเท่ากัน)
- **ผลิตครบแผนแล้ว เครื่องว่าง / ไม่มีงาน** ให้บันทึกหยุดรหัส `NO-ORDER` ทันที
  เช่น `EXEC mfg.usp_downtime_start @machine_id = N'INJ-01', @reason_code = N'NO-ORDER';`
  (ถ้า PLC เปิดรายการหยุดไว้แล้ว คำสั่งนี้จะใส่สาเหตุให้รายการเดิม)
  **เมื่อเริ่มงานใหม่ ให้ปิด**: `EXEC mfg.usp_downtime_stop @machine_id = N'INJ-01';`
  ถ้าไม่บันทึก เวลาว่างจะไปโผล่เป็น "เดินช้า" OEE ต่ำเกินจริง และชีต "แผนเกินกำลัง" จะอ่านผิด
- **หยุดตามแผน** (PM, ประชุม, ไม่มีงาน) ไม่ลด OEE แต่ทำให้ผลิตไม่ทันแผนได้ — ฝ่ายวางแผนต้องหักเวลานี้ออกตอนออกแผน
- ถ้า PLC บันทึกการหยุดอัตโนมัติอยู่แล้ว ให้หน้างาน **ระบุสาเหตุในรายการเดิม** อย่าสร้างรายการใหม่ซ้อน
  (ถ้าซ้อน ระบบจะนับช่วงที่ซ้อนให้รายการที่เริ่มก่อน และแจ้งใน `rpt.v_data_quality`)
- เครื่องที่ **ไม่มีแผนและไม่ได้ผลิต** ในกะนั้น ถูกนับใน OEE เฉพาะเวลาที่เครื่องเสีย (เวลาที่เหลือนับเป็นหยุดตามแผน) — เครื่องที่ `is_active = 0` ไม่ถูกนับเลย
- การหยุดที่ **ยังไม่ระบุสาเหตุ** นับเป็นความสูญเสีย และขึ้นใน Pareto ว่า "ยังไม่ระบุสาเหตุ" — ควรให้ต่ำกว่า 10%
- **เปลี่ยนรูปแบบกะ** (เช่น 2 กะ → 3 กะ) ทำตามกรอบ "เปลี่ยนรูปแบบกะ" ท้ายไฟล์ `03_reference_data.sql` — ห้ามแก้ `@pattern` แล้วรันทั้งไฟล์

### สูตรที่ใช้ (คำนวณจากผลรวม ไม่เฉลี่ย %)
```
Availability = เวลาเดินจริง ÷ เวลาที่ตั้งใจผลิต
Performance  = (ชิ้นทั้งหมด × รอบเวลามาตรฐาน) ÷ เวลาเดินจริง
Quality      = (ชิ้นดี × รอบเวลามาตรฐาน) ÷ (ชิ้นทั้งหมด × รอบเวลามาตรฐาน)
OEE          = (ชิ้นดี × รอบเวลามาตรฐาน) ÷ เวลาที่ตั้งใจผลิต   = A × P × Q
```

---

## งานประจำ

**ทุกวัน (ก่อน 08:10)**
- นำเข้ายอดผลิต/เครื่องหยุดของกะที่จบ (ถ้ายังไม่อัตโนมัติ) — รายงาน 08:45 ใช้ข้อมูลที่เข้าระบบแล้วเท่านั้น
- ระบุสาเหตุการหยุดที่ยังว่าง:
  ```sql
  SELECT event_id, machine_id, start_ts, end_ts FROM mfg.downtime_event WHERE reason_code IS NULL ORDER BY start_ts DESC;
  EXEC mfg.usp_downtime_set_reason @event_id = 125, @reason_code = N'BD-MECH';   -- ใส่เลข event_id จากตารางด้านบน
  ```
- ตรวจคุณภาพข้อมูล (ปัญหาล่าสุด 3 วัน + ปัญหาที่ต้องแก้เสมอ):
  ```sql
  SELECT * FROM rpt.v_data_quality d
  WHERE  d.check_code IN (N'OPEN_STOP_TOO_LONG', N'CALENDAR_ENDING', N'OVERLAPPING_SHIFTS', N'MISSING_CYCLE_TIME', N'FUTURE_TIMESTAMP')
     OR  d.ref_time >= DATEADD(DAY, -3, (SELECT now_local FROM mfg.v_now))
  ORDER BY d.severity, d.ref_time DESC;
  ```
  | check_code | วิธีแก้ |
  |---|---|
  | OPEN_STOP_TOO_LONG | ปิดการหยุดที่ลืม: `EXEC mfg.usp_downtime_stop @machine_id = N'...', @end_ts = '2026-10-21 10:30';` |
  | UNCODED_STOP | `EXEC mfg.usp_downtime_set_reason @event_id = <เลขในคอลัมน์ detail>, @reason_code = N'...';` |
  | MISSING_CYCLE_TIME | เพิ่มรอบเวลามาตรฐานด้วย `usp_import_master` |
  | PRODUCTION_OUTSIDE_SHIFT / CALENDAR_ENDING | ต่อปฏิทินกะ (ดู "ทุกปี") |
  | PRODUCTION_WITHOUT_PLAN | นำเข้าแผนของกะนั้น |
  | PERFORMANCE_UNDER_60 | บันทึก `NO-ORDER` ช่วงที่เครื่องว่าง |
  | PERFORMANCE_OVER_100 | ตรวจรอบเวลามาตรฐานของสินค้านั้น |
  | OVERLAPPING_STOPS | แก้/ลบรายการหยุดที่ซ้อน (เก็บไว้รายการเดียว) |
  | OVERLAPPING_SHIFTS | ดูกรอบ "เปลี่ยนรูปแบบกะ" ใน `03` |
  | FUTURE_TIMESTAMP | ตั้งนาฬิกาเครื่อง/PLC ให้ตรง |

**ทุกสัปดาห์** — ฝ่ายวางแผนนำเข้าแผนสัปดาห์หน้าให้เสร็จก่อนเช้าวันจันทร์ (รายงาน "แผนสัปดาห์หน้าเกินกำลัง" เห็นเฉพาะแผนที่นำเข้าแล้ว)

**มีสินค้าใหม่** — เพิ่มสินค้าและรอบเวลามาตรฐานด้วย `usp_import_master` ก่อนเริ่มผลิต

**ทำ OT วันหยุด / เพิ่มกะ** — (ถ้าวันนั้นอยู่ใน `mfg.holiday` ให้ลบออกก่อน)
```sql
UPDATE mfg.shift_calendar SET is_working = 1, note = N'OT' WHERE prod_date = '2026-10-25' AND shift_code = N'D';
```

**ทุก 5 เดือน** — sign in Tableau Bridge ใหม่ (`tableau/01` ข้อ ข.3)

**ทุกปี (ภายในเดือนพฤศจิกายน)** — 1) ใส่วันหยุดปีหน้าใน `mfg.holiday` 2) ต่อปฏิทินกะ โดยใช้ค่าเสาร์/อาทิตย์เดียวกับใน `03`:
```sql
EXEC mfg.usp_build_shift_calendar @date_from = '2028-01-01', @date_to = '2028-12-31', @work_saturday = 1, @work_sunday = 0;
```

---

## สำรองข้อมูล (สำคัญ — ยอดผลิตย้อนหลังสร้างใหม่ไม่ได้)

1. รันครั้งเดียว: `ALTER DATABASE FactoryBI SET RECOVERY SIMPLE;` (ระบบนี้สำรองรายวันก็พอ log จะได้ไม่โตเรื่อย ๆ)
2. สำรองทุกคืน — รุ่น Express ใช้ Windows Task Scheduler รัน
   ```
   sqlcmd -S .\SQLEXPRESS -E -C -b -Q "BACKUP DATABASE FactoryBI TO DISK = N'D:\Backup\FactoryBI.bak' WITH INIT, CHECKSUM"
   ```
   (รุ่น Express ใส่ `WITH COMPRESSION` ไม่ได้ / รุ่น Standard ใช้ Maintenance Plan ได้)
   โฟลเดอร์ `D:\Backup` ต้องมีอยู่แล้ว และบัญชี service ของ SQL Server ต้องเขียนได้
3. คัดลอกไฟล์ `.bak` ไปเก็บอีกเครื่อง/NAS ทุกวัน และลอง Restore เป็นฐานข้อมูลชื่ออื่นปีละครั้ง
