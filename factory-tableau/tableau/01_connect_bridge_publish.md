# 1) ตั้ง SQL Server, Tableau Bridge และ Publish ข้อมูลขึ้น Tableau Cloud

> ชื่อเมนูอาจต่างกันเล็กน้อยตามเวอร์ชัน ถ้าหาไม่เจอให้ค้นใน help.tableau.com ด้วยคำว่า "Tableau Bridge"

## ก. ตั้งค่า SQL Server (ทำครั้งเดียว — ให้ IT ทำ)

1. **เปิดการ login แบบ SQL Server**
   SSMS → คลิกขวาที่ชื่อเซิร์ฟเวอร์ → *Properties* → *Security* → เลือก **SQL Server and Windows Authentication mode** → OK → รีสตาร์ต service SQL Server
2. **เปิด TCP/IP**
   *SQL Server Configuration Manager* → *SQL Server Network Configuration* → *Protocols for <ชื่อ instance>* → **TCP/IP = Enabled** → รีสตาร์ต service
   - ถ้าเป็น **SQL Server Express** (ชื่อ instance มักเป็น `SQLEXPRESS`) ค่าเริ่มต้นใช้พอร์ตสุ่ม: เข้า *TCP/IP → IP Addresses → IPAll* ลบค่าใน *TCP Dynamic Ports* แล้วใส่ **TCP Port = 1433**
     (เครื่องนั้นต้องไม่มี SQL Server ตัวอื่นใช้พอร์ต 1433 อยู่แล้ว)
3. **เปิด Firewall** บนเครื่อง SQL Server: อนุญาต TCP 1433 ขาเข้า (จากเครื่องที่ลง Bridge และเครื่องที่ใช้ Tableau Desktop)
4. รัน `sql/05_tableau_login.sql` (ถ้ายังไม่ได้รัน)

**ทดสอบจากเครื่องอื่นในโรงงาน:** ติดตั้ง **ไดรเวอร์ Microsoft SQL Server** จากหน้า Driver Download ของ Tableau (tableau.com/support/drivers) ก่อน
แล้วเปิด Tableau Desktop → *Connect → Microsoft SQL Server*
- Server: ใส่ **ชื่อเครื่อง** อย่างเดียว (หรือ `ชื่อเครื่อง, 1433`) — **ไม่ต้องใส่ `\SQLEXPRESS`** เพราะข้อ 2 ตั้งพอร์ต 1433 ไว้แล้ว
  (ถ้าใส่ `\SQLEXPRESS` ต้องเปิด Firewall **UDP 1434** ให้ SQL Server Browser เพิ่ม)
- Database: `FactoryBI`; เลือก *Use a specific username and password* → `tableau_reader`
- **จดชื่อ Server ที่พิมพ์ไว้** ต้องใช้ชื่อเดียวกันนี้ทุก data source และใน Private Network Allowlist (ข้อ ข.4)

## ข. ติดตั้ง Tableau Bridge (ติดตั้งครั้งเดียว แต่ต้อง sign in ใหม่เป็นระยะ)

Tableau Cloud อยู่บนอินเทอร์เน็ต มองไม่เห็น SQL Server ในโรงงาน — **Bridge** คือตัวกลางที่ดึงข้อมูลส่งขึ้น Cloud
(Bridge ต่อออกไปหา Cloud ฝ่ายเดียว ทางพอร์ต 443 และพอร์ต 80 สำหรับตรวจใบรับรอง — ไม่ต้องเปิดพอร์ตขาเข้าจากอินเทอร์เน็ต)

1. เลือกเครื่อง **Windows 10/11 64-bit หรือ Windows Server 2016/2019/2022** (ยังไม่รองรับ Windows Server 2025) ที่เปิดตลอด 24 ชม.
   อยู่ในเครือข่ายโรงงานและมองเห็น SQL Server — Tableau แนะนำให้ใช้ **เครื่องแยกเฉพาะ** ไม่ลงบนเครื่อง SQL Server
   (Bridge สร้างไฟล์ extract ในเครื่องตัวเอง จะแย่ง CPU/RAM/ดิสก์กับฐานข้อมูล) — สเปกแนะนำ 4 vCPU, RAM 16 GB, SSD 150 GB
2. ติดตั้ง **ไดรเวอร์ Microsoft SQL Server** (tableau.com/support/drivers) บนเครื่องนี้ แล้วดาวน์โหลด Tableau Bridge จาก Tableau Cloud (*Settings → Bridge*) หรือหน้า Tableau Bridge Releases มาติดตั้ง
3. เปิด Bridge แล้ว sign in ด้วย **บัญชี Site Administrator ที่ใช้เฉพาะงานนี้** (ไม่ใช่บัญชีส่วนตัวของพนักงาน จะได้ไม่หยุดทำงานเมื่อคนนั้นลาออก)
   - การ sign in ของ Bridge **มีอายุ**: ถ้าไม่ได้ใช้ 14 วัน หรือครบ 180 วัน ต้อง sign in ใหม่ ไม่งั้น refresh และ Live หยุดทั้งหมด → **ตั้งปฏิทินเตือนทุก 5 เดือน**
   - ตรวจว่า *Settings → Authentication → Connected Clients* ติ๊ก **Let clients automatically connect to this Tableau Cloud site** ไว้
4. ใน Tableau Cloud → *Settings → Bridge* (ต้องเป็น Site Admin):
   - **Pooling → Add New Pool** ตั้งชื่อ เช่น `Factory`
   - **Private Network Allowlist → Add New Domain** ใส่ชื่อ Server **ให้ตรงกับที่พิมพ์ในช่อง Server ตอนต่อใน Tableau Desktop ทุกตัวอักษร**
     (เช่น `SRV-SQL01` หรือ `srv-sql01.factory.local` หรือ IP — ห้ามใส่พอร์ต) → *Allow* → เลือก Pool `Factory` → Save
   - ตาราง **Unassigned Clients** → เครื่อง Bridge → **Assign** → เลือก `Factory` → ตรวจสถานะ *Connected*
   - site ใหม่ไม่มี Default pool และ Default pool ผูกกับโดเมนไม่ได้ — ถ้าชื่อ Server ไม่ตรงกับ allowlist งาน refresh จะ error `NO_POOLED_AGENTS_ASSIGNED`
5. ตั้งเวลาของ site: Tableau Cloud → *Settings* → **Site Time Zone for Extracts** → เลือก **(GMT+07:00) Bangkok**
   ถ้าไม่ตั้ง ฟังก์ชัน TODAY()/NOW() และตัวกรอง "วันนี้/เมื่อวาน" ใน extract จะใช้เวลา UTC (ช้ากว่าไทย 7 ชม.)
6. ตั้งเวลาของ **ทุกคนที่จะตั้งตารางเวลา** (refresh / subscription): รูปผู้ใช้มุมขวาบน → *My Account Settings* → **Time zone for scheduled tasks** → (GMT+07:00) Bangkok → Save
   (ข้อ 5 มีผลแค่สูตรวันที่ใน extract ไม่ได้กำหนดว่า subscription 08:30 จะส่งตอนกี่โมง)

ข้อจำกัดที่ควรรู้ของ Bridge: query แบบ Live หมดเวลาที่ 15 นาที และต่อได้พร้อมกัน 16 query ต่อเครื่อง Bridge — view ในชุดนี้เบามาก ไม่เป็นปัญหา

## ค. สร้าง Data Source 4 ตัว แล้ว Publish

ทำใน **Tableau Desktop** (ต้องมีไลเซนส์ Creator) แยก 4 data source ตามงาน:

| ชื่อ Data Source (แนะนำ) | ตารางหลัก | เชื่อม (Relationship) กับ | ใช้ทำ | แบบ |
|---|---|---|---|---|
| `FAC - OEE by Shift` | `rpt.v_oee_shift` | `rpt.v_machine` ด้วย `machine_id` | Dashboard OEE / เวลาหายไปไหน, รายงานเช้า | Extract |
| `FAC - Plan vs Actual Hourly` | `rpt.v_plan_vs_actual_hour` | `rpt.v_machine` ด้วย `machine_id` | Dashboard แผน vs จริง, จอทีวี, แจ้งเตือน | Live (ถ้าทำจอทีวี) หรือ Extract |
| `FAC - Downtime` | `rpt.v_downtime_segment` | `rpt.v_machine` ด้วย `machine_id` | Pareto สาเหตุหยุด, MTTR | Extract |
| `FAC - Plan Capacity` | `rpt.v_plan_capacity` | `rpt.v_machine` ด้วย `machine_id` | แผนข้างหน้าเกินกำลังไหม (ฝ่ายวางแผน) | Extract |

(เสริม: `rpt.v_plan_vs_actual_sku` สำหรับดูแผนต่อสินค้า, `rpt.v_data_quality` สำหรับหน้า Data Health)

**ก่อนเริ่ม:** ตั้ง Tableau Desktop เป็นเมนู **ภาษาอังกฤษ** (*Help → Choose Language → English* แล้วเปิดใหม่)
เพราะ Tableau จะแปลงชื่อคอลัมน์ให้อ่านง่ายเฉพาะตอนใช้เมนูภาษาอังกฤษ และสูตรในไฟล์ `02` เขียนตามชื่อที่แปลงแล้ว
(สร้าง data source เสร็จ จะเปลี่ยนกลับเป็นภาษาไทยก็ได้ ชื่อที่แปลงแล้วติดไปกับ data source)

ขั้นตอนต่อ 1 data source:
1. *Connect → Microsoft SQL Server* → ใส่ Server (ชื่อเดียวกับใน allowlist) / `FactoryBI` / `tableau_reader`
2. ลากตารางหลัก (เช่น `v_oee_shift`) ลงพื้นที่ว่าง **ก่อน** แล้วลาก `v_machine` ตามมา → Tableau จะสร้าง **Relationship** (เส้นยืดหยุ่น) ให้ ตั้งเงื่อนไขเป็น `machine_id = machine_id`
   *ใช้ Relationship ไม่ใช่ Join* — จะได้ไม่มียอดเบิ้ล
3. มุมขวาบนเลือก **Extract** (หรือ Live สำหรับ data source ที่ใช้กับจอทีวี)
4. สร้าง Calculated Field ตามไฟล์ `02_calculated_fields.md` ไว้ **ใน data source นี้** (ทุก Dashboard จะได้ใช้สูตรเดียวกัน)
5. ตั้งชื่อ data source ตามตารางด้านบน
6. *Server → Publish Data Source → Tableau Cloud*
   - Authentication: **Embedded password**
   - ถ้าเป็น Extract: ตั้ง **Refresh schedule ทุก 1 ชั่วโมง** (Tableau Cloud refresh ได้ถี่สุดชั่วโมงละครั้ง) — ข้อมูลชุดนี้เล็ก ใช้ Full refresh ได้เลย
   - Tableau Cloud จะส่งงาน refresh ผ่าน Bridge ให้เอง **เมื่อชื่อ Server ตรงกับ Private Network Allowlist ของ pool ที่มีเครื่อง Bridge อยู่**
7. Certify: Tableau Cloud → *Explore → All Data Sources* → ปุ่ม … หลังชื่อ data source → **Data Labels → Certification** → ติ๊ก *Certified* → Save
   (ทำได้เฉพาะ Site Admin หรือ Creator/Explorer (can publish) ที่เป็นเจ้าของหรือ Project Leader ของ project นั้น) — ให้ทุกคนรู้ว่าตัวนี้คือตัวจริง
8. สร้าง Dashboard โดยต่อกับ **published data source** (*Data → New Data Source → Tableau Server/Cloud*) ไม่ต่อ SQL ตรงอีก

## ง. ข้อมูลสดแค่ไหน

| แบบ | ความสด | ใช้กับ |
|---|---|---|
| Extract refresh ทุกชั่วโมง | ช้าสุดประมาณ 1 ชม. | รายงานเช้า, OEE, Pareto, แจ้งเตือน |
| Live ผ่าน Bridge | ตาม **Data Freshness Policy** ของ workbook — ค่าเริ่มต้นของ Tableau Cloud ใช้ข้อมูลที่แคชไว้ได้นานถึง 12 ชม. **ต้องตั้งเป็นทุก 5 นาที** (วิธีตั้งอยู่ในไฟล์ `03` หัวข้อ ④) | จอทีวีหน้าไลน์ (แผน vs จริงกะปัจจุบัน) |

ทั้งสองแบบไม่ใช่ระบบเตือนฉุกเฉินแบบวินาทีต่อวินาที — งานแบบนั้นให้ใช้ SCADA/ไฟ Andon หน้าเครื่อง
