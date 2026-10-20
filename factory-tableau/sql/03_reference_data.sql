/* =====================================================================
   03_reference_data.sql  —  ข้อมูลตั้งต้น: กะ, เวลาพัก, รหัสสาเหตุหยุด, ปฏิทินกะ

   >>> แก้ค่าในไฟล์นี้ให้ตรงกับโรงงานก่อนรัน <<<
     - ค่าเริ่มต้นคือ 2 กะ x 12 ชม. (08:00-20:00 และ 20:00-08:00) พัก 1 ชม.
     - ทำงาน จันทร์-เสาร์ หยุดอาทิตย์
   รันซ้ำได้: เพิ่มเฉพาะรายการที่ยังไม่มี ไม่ทับของเดิม
   ===================================================================== */

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
BEGIN
    RAISERROR(N'กรุณาเลือกฐานข้อมูลของโรงงาน (เช่น FactoryBI) ก่อนรันสคริปต์นี้', 16, 1);
    SET NOEXEC ON;
END
GO

/* ---------------------------------------------------------------------
   1) กะทำงาน
   --------------------------------------------------------------------- */
INSERT INTO mfg.shift_definition (shift_code, shift_name_th, start_time, duration_min, start_day_offset, sort_order)
SELECT v.shift_code, v.shift_name_th, v.start_time, v.duration_min, v.start_day_offset, v.sort_order
FROM (VALUES
    (N'D', N'กะเช้า', CAST('08:00' AS TIME(0)), 720, 0, 1),
    (N'N', N'กะดึก', CAST('20:00' AS TIME(0)), 720, 0, 2)
    /* ถ้าเป็น 3 กะ x 8 ชม. ให้ใช้ชุดนี้แทน 2 บรรทัดบน
    (N'A', N'กะ A', CAST('07:00' AS TIME(0)), 480, 0, 1),
    (N'B', N'กะ B', CAST('15:00' AS TIME(0)), 480, 0, 2),
    (N'C', N'กะ C', CAST('23:00' AS TIME(0)), 480, 0, 3)
    */
) v (shift_code, shift_name_th, start_time, duration_min, start_day_offset, sort_order)
WHERE NOT EXISTS (SELECT 1 FROM mfg.shift_definition s WHERE s.shift_code = v.shift_code);
GO

/* ---------------------------------------------------------------------
   2) เวลาพัก: offset_min = เริ่มพักหลังเริ่มกะกี่นาที
      กะเช้า 08:00 + 240 นาที = พัก 12:00-13:00
      กะดึก 20:00 + 240 นาที = พัก 00:00-01:00
      ถ้ามีพักย่อย เช่น 10:00-10:10 ให้เพิ่มแถว break_no = 2, offset_min = 120, break_min = 10
      ถ้าเครื่องเดินต่อตอนพัก (มีคนเปลี่ยนแทน) ไม่ต้องใส่เวลาพัก
   --------------------------------------------------------------------- */
INSERT INTO mfg.shift_break_definition (shift_code, break_no, offset_min, break_min)
SELECT v.shift_code, v.break_no, v.offset_min, v.break_min
FROM (VALUES
    (N'D', 1, 240, 60),
    (N'N', 1, 240, 60)
) v (shift_code, break_no, offset_min, break_min)
WHERE EXISTS (SELECT 1 FROM mfg.shift_definition s WHERE s.shift_code = v.shift_code)
  AND NOT EXISTS (SELECT 1 FROM mfg.shift_break_definition b WHERE b.shift_code = v.shift_code AND b.break_no = v.break_no);
GO

/* ---------------------------------------------------------------------
   3) รหัสสาเหตุเครื่องหยุด (ปรับชื่อ/เพิ่ม/ลด ได้ แต่ควรมีไม่เกิน ~20 รหัส)
      loss_category ดูคำอธิบายใน 01_schema.sql
   --------------------------------------------------------------------- */
INSERT INTO mfg.downtime_reason (reason_code, reason_name_th, reason_name_en, loss_category, responsible_dept, sort_order)
SELECT v.reason_code, v.reason_name_th, v.reason_name_en, v.loss_category, v.responsible_dept, v.sort_order
FROM (VALUES
    (N'PM-PLAN',  N'ซ่อมบำรุงตามแผน (PM)',            N'Planned maintenance',        N'PLANNED',    N'ซ่อมบำรุง', 10),
    (N'NO-ORDER', N'ไม่มีออร์เดอร์/ไม่มีแผนผลิต',       N'No order',                   N'PLANNED',    N'วางแผน',    11),
    (N'MEETING',  N'ประชุม/อบรม/5ส ตามแผน',            N'Planned meeting/training',   N'PLANNED',    N'ผลิต',      12),
    (N'BD-MECH',  N'เครื่องเสีย - กลไก',               N'Breakdown - mechanical',     N'BREAKDOWN',  N'ซ่อมบำรุง', 20),
    (N'BD-ELEC',  N'เครื่องเสีย - ไฟฟ้า/คอนโทรล',      N'Breakdown - electrical',     N'BREAKDOWN',  N'ซ่อมบำรุง', 21),
    (N'BD-TOOL',  N'แม่พิมพ์/จิ๊กเสีย',                N'Breakdown - tooling',        N'BREAKDOWN',  N'ซ่อมบำรุง', 22),
    (N'SETUP',    N'เปลี่ยนรุ่น/ตั้งเครื่อง',            N'Changeover / setup',         N'SETUP',      N'ผลิต',      30),
    (N'ADJUST',   N'ปรับตั้งระหว่างผลิต',               N'Adjustment',                 N'SETUP',      N'ผลิต',      31),
    (N'MINOR',    N'หยุดเล็กน้อย (ชิ้นงานติด/เซนเซอร์)', N'Minor stop / jam',           N'MINOR_STOP', N'ผลิต',      40),
    (N'MAT-WAIT', N'รอวัตถุดิบ/รอชิ้นงาน',              N'Waiting material',           N'MATERIAL',   N'วางแผน',    50),
    (N'MAT-NG',   N'วัตถุดิบไม่ได้คุณภาพ',              N'Material defect',            N'MATERIAL',   N'จัดซื้อ/QC', 51),
    (N'NO-OPR',   N'ไม่มีพนักงานคุมเครื่อง',             N'No operator',                N'MANPOWER',   N'ผลิต',      60),
    (N'QC-HOLD',  N'รอ QC ตรวจ/หยุดเพราะของเสีย',        N'Quality hold',               N'QUALITY',    N'QC',        70),
    (N'UTILITY',  N'ไฟดับ/ลมไม่พอ/น้ำหล่อเย็น',          N'Utility failure',            N'OTHER',      N'Facility',  80),
    (N'OTHER',    N'อื่น ๆ (ระบุในหมายเหตุ)',            N'Other',                      N'OTHER',      NULL,         99)
) v (reason_code, reason_name_th, reason_name_en, loss_category, responsible_dept, sort_order)
WHERE NOT EXISTS (SELECT 1 FROM mfg.downtime_reason r WHERE r.reason_code = v.reason_code);
GO

/* ---------------------------------------------------------------------
   4) วันหยุดโรงงาน (ตัวอย่าง — ใส่ตามปฏิทินของโรงงานเองก่อนสร้างปฏิทินกะ)
   --------------------------------------------------------------------- */
/*
INSERT INTO mfg.holiday (holiday_date, holiday_name) VALUES
    ('2027-01-01', N'วันขึ้นปีใหม่'),
    ('2027-04-13', N'สงกรานต์'),
    ('2027-04-14', N'สงกรานต์'),
    ('2027-04-15', N'สงกรานต์');
*/

/* ---------------------------------------------------------------------
   5) สร้างปฏิทินกะ: ตั้งแต่ต้นเดือนเมื่อ 3 เดือนก่อน ถึงสิ้นปีหน้า
      ถ้าจะนำเข้าข้อมูลย้อนหลังเก่ากว่านั้น ให้รันเพิ่มเอง เช่น
      EXEC mfg.usp_build_shift_calendar '2025-01-01', '2025-12-31';
   --------------------------------------------------------------------- */
DECLARE @today DATE = (SELECT CAST(now_local AS DATE) FROM mfg.v_now);
DECLARE @from  DATE = DATEADD(MONTH, -3, DATEFROMPARTS(YEAR(@today), MONTH(@today), 1));
DECLARE @to    DATE = DATEFROMPARTS(YEAR(@today) + 1, 12, 31);

EXEC mfg.usp_build_shift_calendar
     @date_from     = @from,
     @date_to       = @to,
     @work_saturday = 1,   -- 1 = เสาร์ทำงาน
     @work_sunday   = 0;   -- 0 = อาทิตย์หยุด
GO

PRINT N'03_reference_data.sql เสร็จ';
GO
SET NOEXEC OFF;
GO
