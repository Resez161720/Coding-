# 1) ตั้ง SQL Server, Tableau Bridge และ Publish ข้อมูลขึ้น Tableau Cloud

> ชื่อเมนูอาจต่างกันเล็กน้อยตามเวอร์ชัน ถ้าหาไม่เจอให้ค้นใน help.tableau.com ด้วยคำว่า "Tableau Bridge"

## ก. ตั้งค่า SQL Server (ทำครั้งเดียว — ให้ IT ทำ)

1. **เปิดการ login แบบ SQL Server**
   SSMS → คลิกขวาที่ชื่อเซิร์ฟเวอร์ → *Properties* → *Security* → เลือก **SQL Server and Windows Authentication mode** → OK → รีสตาร์ต service SQL Server
2. **เปิด TCP/IP**
   *SQL Server Configuration Manager* → *SQL Server Network Configuration* → *Protocols for <ชื่อ instance>* → **TCP/IP = Enabled** → รีสตาร์ต service
   - ถ้าเป็น **SQL Server Express** (ชื่อ instance มักเป็น `SQLEXPRESS`) ค่าเริ่มต้นใช้พอร์ตสุ่ม: เข้า *TCP/IP → IP Addresses → IPAll* ลบค่าใน *TCP Dynamic Ports* แล้วใส่ **TCP Port = 1433**
3. **เปิด Firewall** บนเครื่อง SQL Server: อนุญาต TCP 1433 ขาเข้า (จากเครื่องที่ลง Bridge และเครื่องที่ใช้ Tableau Desktop)
4. รัน `sql/05_tableau_login.sql` (ถ้ายังไม่ได้รัน)

ทดสอบจากเครื่องอื่นในโรงงาน: เปิด Tableau Desktop → *Connect → Microsoft SQL Server* ใส่ชื่อเครื่อง (หรือ `ชื่อเครื่อง\SQLEXPRESS`), ฐานข้อมูล `FactoryBI`, เลือก *Use a specific username and password* → `tableau_reader`

## ข. ติดตั้ง Tableau Bridge (ทำครั้งเดียว)

Tableau Cloud อยู่บนอินเทอร์เน็ต มองไม่เห็น SQL Server ในโรงงาน — **Bridge** คือตัวกลางที่ดึงข้อมูลส่งขึ้น Cloud
(Bridge ต่อออกไปหา Cloud ฝ่ายเดียว ไม่ต้องเปิดพอร์ตขาเข้าจากอินเทอร์เน็ต)

1. เลือกเครื่อง **Windows ที่เปิดตลอด 24 ชม.** อยู่ในเครือข่ายโรงงานและมองเห็น SQL Server (จะเป็นเครื่องเดียวกับ SQL Server ก็ได้)
2. ดาวน์โหลด Tableau Bridge จาก Tableau Cloud (*Settings → Bridge*) หรือหน้า Tableau Bridge Releases แล้วติดตั้ง
3. เปิด Bridge แล้ว **sign in ด้วยบัญชี Site Administrator** ของ Tableau Cloud
4. ใน Tableau Cloud → *Settings → Bridge*:
   - ตรวจว่าเครื่องนี้อยู่ใน **pool** (เช่น Default pool) และสถานะ *Connected*
   - เพิ่มชื่อเครื่อง/โดเมนของ SQL Server ใน **Private Network Allowlist** ของ pool นั้น
5. ตั้งเวลาให้ถูก: Tableau Cloud → *Settings* → **Site Time Zone for Extracts** → เลือก **(GMT+07:00) Bangkok**
   ถ้าไม่ตั้ง ฟังก์ชัน TODAY()/NOW() และตัวกรอง "วันนี้" ใน extract จะใช้เวลา UTC (ช้ากว่าไทย 7 ชม.)

ข้อจำกัดที่ควรรู้ของ Bridge: query แบบ Live หมดเวลาที่ 15 นาที และต่อได้พร้อมกัน 16 query ต่อเครื่อง Bridge — view ในชุดนี้เบามาก ไม่เป็นปัญหา

## ค. สร้าง Data Source 4 ตัว แล้ว Publish

ทำใน **Tableau Desktop** (ต้องมีไลเซนส์ Creator) แยก 4 data source ตามงาน:

| ชื่อ Data Source (แนะนำ) | ตารางหลัก | เชื่อม (Relationship) กับ | ใช้ทำ | แบบ |
|---|---|---|---|---|
| `FAC - OEE by Shift` | `rpt.v_oee_shift` | `rpt.v_machine` ด้วย `machine_id` | Dashboard OEE/คอขวด, รายงานเช้า | Extract |
| `FAC - Plan vs Actual Hourly` | `rpt.v_plan_vs_actual_hour` | `rpt.v_machine` ด้วย `machine_id` | Dashboard แผน vs จริง, จอทีวี, แจ้งเตือน | Live (ถ้าทำจอทีวี) หรือ Extract |
| `FAC - Downtime` | `rpt.v_downtime_segment` | `rpt.v_machine` ด้วย `machine_id` | Pareto สาเหตุหยุด, MTTR | Extract |
| `FAC - Plan Capacity` | `rpt.v_plan_capacity` | `rpt.v_machine` ด้วย `machine_id` | แผนข้างหน้าเกินกำลังไหม (ฝ่ายวางแผน) | Extract |

(เสริม: `rpt.v_plan_vs_actual_sku` สำหรับดูแผนต่อสินค้า, `rpt.v_data_quality` สำหรับหน้า Data Health)

ขั้นตอนต่อ 1 data source:
1. *Connect → Microsoft SQL Server* → ใส่เซิร์ฟเวอร์ / `FactoryBI` / `tableau_reader`
2. ลากตารางหลัก (เช่น `v_oee_shift`) ลงพื้นที่ว่าง แล้วลาก `v_machine` ตามมา → Tableau จะสร้าง **Relationship** (เส้นยืดหยุ่น) ให้ ตั้งเงื่อนไขเป็น `machine_id = machine_id`
   *ใช้ Relationship ไม่ใช่ Join* — จะได้ไม่มียอดเบิ้ล
3. มุมขวาบนเลือก **Extract** (หรือ Live สำหรับ data source ที่ใช้กับจอทีวี)
4. สร้าง Calculated Field ตามไฟล์ `02_calculated_fields.md` ไว้ **ใน data source นี้** (ทุก Dashboard จะได้ใช้สูตรเดียวกัน)
5. ตั้งชื่อ data source ตามตารางด้านบน
6. *Server → Publish Data Source → Tableau Cloud*
   - Authentication: **Embedded password**
   - ถ้าเป็น Extract: ตั้ง **Refresh schedule ทุก 1 ชั่วโมง** (Tableau Cloud refresh ได้ถี่สุดชั่วโมงละครั้ง) — ข้อมูลชุดนี้เล็ก ใช้ Full refresh ได้เลย
   - Tableau Cloud จะส่งงาน refresh ผ่าน Bridge ให้เองเมื่อเห็นว่าเป็นฐานข้อมูลในเครือข่ายโรงงาน
7. ใน Tableau Cloud เปิด data source ที่ publish แล้ว → เมนู *…* → **Certify** (ให้ทุกคนรู้ว่าตัวนี้คือตัวจริง)
8. สร้าง Dashboard โดยต่อกับ **published data source** (*Data → New Data Source → Tableau Server/Cloud*) ไม่ต่อ SQL ตรงอีก

## ง. ข้อมูลสดแค่ไหน

| แบบ | ความสด | ใช้กับ |
|---|---|---|
| Extract refresh ทุกชั่วโมง | ช้าสุดประมาณ 1 ชม. | รายงานเช้า, OEE, Pareto, แจ้งเตือน |
| Live ผ่าน Bridge | ทุกครั้งที่หน้าจอโหลดใหม่ | จอทีวีหน้าไลน์ (แผน vs จริงกะปัจจุบัน) |

ทั้งสองแบบไม่ใช่ระบบเตือนฉุกเฉินแบบวินาทีต่อวินาที — งานแบบนั้นให้ใช้ SCADA/ไฟ Andon หน้าเครื่อง
