# ชุดเริ่มต้น SQL Server + Tableau Cloud สำหรับโรงงาน

เป้าหมาย: แก้ 2 ปัญหาหลัก — **ผลิตไม่ทันแผน** และ **ทำรายงานช้า**
โดยให้ข้อมูลไหลจาก SQL Server ในโรงงาน → Tableau Bridge → Tableau Cloud แล้วส่งรายงาน/แจ้งเตือนอัตโนมัติ

```
เครื่องจักร / แบบฟอร์ม / ระบบเดิม
        │  (procedure หรือ 06_load_from_existing)
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
| `sql/02_views_and_procs.sql` | สร้าง view สำหรับ Tableau (OEE, แผน vs จริง, Pareto) และ procedure บันทึกข้อมูล |
| `sql/03_reference_data.sql` | ใส่กะ/เวลาพัก/รหัสสาเหตุหยุด และสร้างปฏิทินกะ — **แก้ให้ตรงโรงงานก่อนรัน** |
| `sql/04_sample_data.sql` | ข้อมูลตัวอย่าง 30 เครื่อง 28 วัน (ใช้กับ `FactoryBI_Demo` เท่านั้น) |
| `sql/05_tableau_login.sql` | สร้างผู้ใช้ `tableau_reader` อ่านได้เฉพาะ view |
| `sql/06_load_from_existing_TEMPLATE.sql` | แม่แบบดึงข้อมูลจากตารางเดิมของโรงงาน + นำเข้าแผนจาก Excel |
| `tableau/01_connect_bridge_publish.md` | ตั้ง SQL Server, Tableau Bridge, เชื่อมต่อและ Publish |
| `tableau/02_calculated_fields.md` | สูตรทั้งหมดที่ต้องสร้างใน Tableau (copy ไปวางได้เลย) |
| `tableau/03_dashboards_alerts.md` | ขั้นตอนสร้าง Dashboard 3 ตัว + จอทีวี + รายงานอัตโนมัติ + แจ้งเตือน |

ต้องใช้ **SQL Server 2016 SP1 ขึ้นไป** (รุ่น Express ก็ใช้ได้)

---

## เริ่มต้น: ลองกับข้อมูลตัวอย่างก่อน (ประมาณ 15 นาที)

เปิด **SQL Server Management Studio (SSMS)** แล้วทำตามลำดับ
(ทุกไฟล์: File → Open → เลือกไฟล์ → เลือกฐานข้อมูลที่ช่อง *Available Databases* บนแถบเครื่องมือ → กด **Execute**)

1. `00_create_databases.sql` (ฐานข้อมูลอะไรก็ได้ เช่น master)
2. เลือก **FactoryBI_Demo** แล้วรัน `01_schema.sql` → `02_views_and_procs.sql` → `03_reference_data.sql` → `04_sample_data.sql`
3. แก้รหัสผ่านใน `05_tableau_login.sql` แล้วรันใน **FactoryBI_Demo**
4. ลองดูผล:
   ```sql
   SELECT TOP 20 * FROM rpt.v_oee_shift ORDER BY shift_start DESC;
   SELECT * FROM rpt.v_plan_vs_actual_hour WHERE shifts_ago = 0 AND machine_id = N'CNC-03' ORDER BY slot_no;
   SELECT * FROM rpt.v_data_quality;
   ```
5. ไปต่อที่ `tableau/01_connect_bridge_publish.md` แล้วสร้าง Dashboard จากข้อมูลตัวอย่าง

ข้อมูลตัวอย่างจำลองสถานการณ์ไว้ให้หาเจอใน Dashboard: **CNC-03 เป็นคอขวด** (เสียบ่อย),
**PRS-02 ได้แผนเกินกำลังผลิต**, **PRS-05 เดินช้า**, **INJ-04 ของเสียสูง**

> ลองเสร็จแล้วอยากเริ่มใหม่: ลบฐานข้อมูล `FactoryBI_Demo` ทิ้ง แล้วรันข้อ 1–3 ใหม่

---

## ใช้กับข้อมูลจริง

1. แก้ `03_reference_data.sql` ให้ตรงกับโรงงาน
   - **กะ**: เวลาเริ่ม, ความยาว (ต้องเริ่มตรงชั่วโมง เช่น 08:00 และยาวเป็นชั่วโมงเต็ม)
   - **เวลาพัก**: นาทีที่เริ่มพักนับจากต้นกะ และพักกี่นาที
   - **วันทำงาน**: `@work_saturday`, `@work_sunday` และวันหยุดโรงงานในตาราง `mfg.holiday`
   - **รหัสสาเหตุหยุด**: ไม่ควรเกิน ~20 รหัส ให้ฝ่ายผลิต/ซ่อมบำรุง/QC ตกลงร่วมกัน
2. เลือกฐานข้อมูล **FactoryBI** แล้วรัน `01` → `02` → `03` → `05` (**ไม่ต้องรัน 04**)
3. ใส่ข้อมูลหลัก (ทำครั้งเดียว แก้ใน SSMS ได้: คลิกขวาที่ตาราง → *Edit Top 200 Rows* หรือ INSERT)
   - `mfg.machine` — เครื่องทั้ง 30 ตัว (`is_active = 0` สำหรับเครื่องที่ไม่ได้ใช้)
   - `mfg.product` — รหัสสินค้า
   - `mfg.std_cycle_time` — **รอบเวลามาตรฐาน (วินาที/ชิ้น) ต่อสินค้า x เครื่อง** ใช้ค่าที่เร็วที่สุดที่ทำได้จริงอย่างสม่ำเสมอ ไม่ใช่ค่าจากแคตตาล็อก
4. ให้ข้อมูลประจำวันไหลเข้า เลือกวิธีที่เหมาะ
   | ข้อมูล | ถ้ามีระบบเดิมเก็บใน SQL อยู่แล้ว | ถ้ายังไม่มี |
   |---|---|---|
   | ยอดผลิตรายชั่วโมง | `06_load_from_existing_TEMPLATE.sql` | PLC/Gateway เรียก `mfg.usp_upsert_production_hour` หรือกรอกผ่านแบบฟอร์ม |
   | เครื่องหยุด | `06_load_from_existing_TEMPLATE.sql` | `mfg.usp_downtime_start` / `usp_downtime_stop` / `usp_downtime_set_reason` |
   | แผนการผลิต | — | นำเข้าจาก Excel (วิธีอยู่ท้ายไฟล์ `06`) |
5. ตรวจคุณภาพข้อมูลทุกวัน: `SELECT * FROM rpt.v_data_quality ORDER BY severity;`

### กติกาสำคัญของข้อมูล
- เวลาทั้งหมดเก็บเป็น **เวลาไทย** (ไม่ใช่ UTC)
- **กะดึกที่ข้ามเที่ยงคืน** นับเป็นวันผลิตเดียวกับวันที่เริ่มกะ (เช่น กะดึกคืนวันที่ 20 ที่จบ 08:00 วันที่ 21 = วันผลิต 20)
- **เวลาพัก** ถูกหักออกให้อัตโนมัติ ไม่ต้องบันทึกเป็นเครื่องหยุด
- **เปลี่ยนรุ่น/ตั้งเครื่อง** นับเป็นความสูญเสีย (ตามมาตรฐาน OEE) ไม่ใช่หยุดตามแผน
- เครื่องที่ **ไม่มีแผนและไม่ได้ผลิต** ในกะนั้น จะไม่ถูกนำมาคิด OEE
- การหยุดที่ **ยังไม่ระบุสาเหตุ** นับเป็นความสูญเสีย และขึ้นใน Pareto ว่า "ยังไม่ระบุสาเหตุ" — ควรให้ต่ำกว่า 10%

### สูตรที่ใช้ (คำนวณจากผลรวม ไม่เฉลี่ย %)
```
Availability = เวลาเดินจริง ÷ เวลาที่ตั้งใจผลิต
Performance  = (ชิ้นทั้งหมด × รอบเวลามาตรฐาน) ÷ เวลาเดินจริง
Quality      = (ชิ้นดี × รอบเวลามาตรฐาน) ÷ (ชิ้นทั้งหมด × รอบเวลามาตรฐาน)
OEE          = (ชิ้นดี × รอบเวลามาตรฐาน) ÷ เวลาที่ตั้งใจผลิต   = A × P × Q
```
