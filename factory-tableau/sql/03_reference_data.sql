/* =====================================================================
   03_reference_data.sql  —  ข้อมูลตั้งต้น: กะ, เวลาพัก, รหัสสาเหตุหยุด, ปฏิทินกะ

   >>> แก้ค่าในไฟล์นี้ให้ตรงกับโรงงานก่อนรัน <<<
     - รูปแบบกะ: แก้ @pattern ในข้อ 1-2 (ค่าเริ่มต้น 2 กะ x 12 ชม. พัก 1 ชม.)
     - วันทำงาน: แก้ @work_saturday / @work_sunday ในข้อ 5 (ค่าเริ่มต้น จันทร์-เสาร์ หยุดอาทิตย์)
   รันซ้ำได้: เพิ่มเฉพาะรายการที่ยังไม่มี ไม่ทับของเดิม และสร้างปฏิทินต่อจากวันสุดท้ายที่มีอยู่
   ถ้าจะ "เปลี่ยนรูปแบบกะ" หลังจากใช้งานไปแล้ว ห้ามรันทั้งไฟล์ ให้ทำตามกรอบท้ายไฟล์
   ===================================================================== */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
BEGIN
    RAISERROR(N'กรุณาเลือกฐานข้อมูลของโรงงาน (เช่น FactoryBI) ก่อนรันสคริปต์นี้', 16, 1);
    SET NOEXEC ON;
END
GO

/* ---------------------------------------------------------------------
   1-2) กะทำงาน และเวลาพัก — เลือกรูปแบบกะที่บรรทัด @pattern บรรทัดเดียว
     '2x12'     = กะเช้า 08:00-20:00 / กะดึก 20:00-08:00 พัก 1 ชม. (ค่าเริ่มต้น)
     '3x8'      = กะ A 07:00 / B 15:00 / C 23:00 พัก 30 นาที (กะ C นับเป็นวันผลิตของวันที่เริ่มกะ)
     '3x8_next' = เหมือน 3x8 แต่นับกะ C 23:00 เป็น "กะแรกของวันผลิตถัดไป"
   ถ้าเวลาไม่ตรงกับโรงงาน ให้แก้ตัวเลขในแถวของรูปแบบที่เลือก
     - เวลาเริ่มกะต้องตรงชั่วโมง และความยาวกะ (นาที) ต้องเป็นชั่วโมงเต็ม
     - เวลาพัก: offset_min = เริ่มพักหลังเริ่มกะกี่นาที เช่น กะเช้า 08:00 + 240 = พัก 12:00
       ถ้ามีพักย่อย ให้เพิ่มแถว break_no = 2 ; ถ้าเครื่องเดินต่อตอนพัก (มีคนเปลี่ยนแทน) ให้ลบแถวพักของกะนั้น
   --------------------------------------------------------------------- */
DECLARE @pattern VARCHAR(10) = '2x12';   -- <<< แก้ตรงนี้: '2x12' | '3x8' | '3x8_next'

INSERT INTO mfg.shift_definition (shift_code, shift_name_th, start_time, duration_min, start_day_offset, sort_order)
SELECT v.shift_code, v.shift_name_th, v.start_time, v.duration_min, v.start_day_offset, v.sort_order
FROM (VALUES
    ('2x12',     N'D', N'กะเช้า', CAST('08:00' AS TIME(0)), 720,  0, 1),
    ('2x12',     N'N', N'กะดึก', CAST('20:00' AS TIME(0)), 720,  0, 2),
    ('3x8',      N'A', N'กะ A',  CAST('07:00' AS TIME(0)), 480,  0, 1),
    ('3x8',      N'B', N'กะ B',  CAST('15:00' AS TIME(0)), 480,  0, 2),
    ('3x8',      N'C', N'กะ C',  CAST('23:00' AS TIME(0)), 480,  0, 3),
    ('3x8_next', N'C', N'กะ C',  CAST('23:00' AS TIME(0)), 480, -1, 1),
    ('3x8_next', N'A', N'กะ A',  CAST('07:00' AS TIME(0)), 480,  0, 2),
    ('3x8_next', N'B', N'กะ B',  CAST('15:00' AS TIME(0)), 480,  0, 3)
) v (pattern, shift_code, shift_name_th, start_time, duration_min, start_day_offset, sort_order)
WHERE v.pattern = @pattern
  AND NOT EXISTS (SELECT 1 FROM mfg.shift_definition s WHERE s.shift_code = v.shift_code);

INSERT INTO mfg.shift_break_definition (shift_code, break_no, offset_min, break_min)
SELECT v.shift_code, v.break_no, v.offset_min, v.break_min
FROM (VALUES
    ('2x12',     N'D', 1, 240, 60),
    ('2x12',     N'N', 1, 240, 60),
    ('3x8',      N'A', 1, 240, 30),
    ('3x8',      N'B', 1, 240, 30),
    ('3x8',      N'C', 1, 240, 30),
    ('3x8_next', N'A', 1, 240, 30),
    ('3x8_next', N'B', 1, 240, 30),
    ('3x8_next', N'C', 1, 240, 30)
) v (pattern, shift_code, break_no, offset_min, break_min)
WHERE v.pattern = @pattern
  AND EXISTS (SELECT 1 FROM mfg.shift_definition s WHERE s.shift_code = v.shift_code)
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
   4) วันหยุดโรงงาน (ตัวอย่าง — ใส่ตามปฏิทินของโรงงาน)
      ใส่ภายหลังก็ได้ แล้วรัน mfg.usp_build_shift_calendar ช่วงวันที่นั้นซ้ำ ระบบจะปิดกะวันหยุดให้
      ถ้าตัดสินใจทำงานในวันที่อยู่ในตารางนี้ ให้ลบวันนั้นออกจาก mfg.holiday ก่อน แล้วแก้ is_working = 1 ใน mfg.shift_calendar
   --------------------------------------------------------------------- */
/*
INSERT INTO mfg.holiday (holiday_date, holiday_name) VALUES
    ('2027-01-01', N'วันขึ้นปีใหม่'),
    ('2027-04-13', N'สงกรานต์'),
    ('2027-04-14', N'สงกรานต์'),
    ('2027-04-15', N'สงกรานต์');
*/

/* ---------------------------------------------------------------------
   5) สร้างปฏิทินกะ ถึงสิ้นปีหน้า
      ครั้งแรก: เริ่มตั้งแต่ต้นเดือนเมื่อ 3 เดือนก่อน / ครั้งต่อไป: ต่อจากวันสุดท้ายที่มีอยู่
      ถ้าจะนำเข้าข้อมูลย้อนหลังเก่ากว่านั้น ให้รันเพิ่มเอง (ใช้ค่าเสาร์/อาทิตย์เดียวกับด้านล่าง) เช่น
      EXEC mfg.usp_build_shift_calendar '2025-01-01', '2025-12-31', @work_saturday = 1, @work_sunday = 0;
   --------------------------------------------------------------------- */
DECLARE @today DATE = (SELECT CAST(now_local AS DATE) FROM mfg.v_now);
DECLARE @to    DATE = DATEFROMPARTS(YEAR(@today) + 1, 12, 31);
DECLARE @from  DATE = ISNULL((SELECT DATEADD(DAY, 1, MAX(prod_date)) FROM mfg.shift_calendar),
                             DATEADD(MONTH, -3, DATEFROMPARTS(YEAR(@today), MONTH(@today), 1)));

IF @from <= @to
    EXEC mfg.usp_build_shift_calendar
         @date_from     = @from,
         @date_to       = @to,
         @work_saturday = 1,   -- 1 = เสาร์ทำงาน, 0 = เสาร์หยุด
         @work_sunday   = 0;   -- 1 = อาทิตย์ทำงาน, 0 = อาทิตย์หยุด
ELSE
    PRINT N'ปฏิทินกะมีถึงสิ้นปีหน้าแล้ว';
GO

/* =====================================================================
   เปลี่ยนรูปแบบกะ (เช่น 2 กะ → 3 กะ) หลังจากใช้งานไปแล้ว — ห้ามรันไฟล์นี้ซ้ำทั้งไฟล์ ให้ทำ 2 ขั้น
   (กะแบบใหม่ต้องใช้รหัสกะต่างจากเดิม เช่น เดิม D/N ใหม่ A/B/C)

   ขั้น 1: แก้ @pattern ในข้อ 1-2 เป็นรูปแบบใหม่ → ลากคลุมเฉพาะข้อ 1-2 (ตั้งแต่ DECLARE @pattern ถึง GO) → Execute
   ขั้น 2: แก้ @change_date และรหัสกะเดิมด้านล่าง → ลากคลุมเฉพาะคำสั่ง (ไม่รวมบรรทัดคำอธิบายนี้) → Execute

DECLARE @change_date DATE = '2026-11-01';                    -- วันผลิตแรกที่ใช้กะแบบใหม่
DECLARE @old TABLE (shift_code NVARCHAR(10));
INSERT INTO @old VALUES (N'D'), (N'N');                      -- รหัสกะเดิม
-- ต้องไม่มีแผนของกะเดิมตั้งแต่วันเปลี่ยน
IF EXISTS (SELECT 1 FROM mfg.production_plan p JOIN @old o ON o.shift_code = p.shift_code WHERE p.prod_date >= @change_date)
BEGIN
    SELECT p.* FROM mfg.production_plan p JOIN @old o ON o.shift_code = p.shift_code WHERE p.prod_date >= @change_date;
    RAISERROR(N'ยังมีแผนของกะเดิมหลังวันเปลี่ยน (ดูตารางผลลัพธ์) ให้ลบ หรือนำเข้าแผนใหม่ตามกะใหม่ก่อน', 16, 1);
    RETURN;
END;
UPDATE s SET is_active = 0 FROM mfg.shift_definition s JOIN @old o ON o.shift_code = s.shift_code;
DECLARE @first_new_start DATETIME2(0) =
    (SELECT MIN(DATEADD(HOUR, DATEPART(HOUR, start_time), DATEADD(DAY, start_day_offset, CAST(@change_date AS DATETIME2(0)))))
     FROM mfg.shift_definition WHERE is_active = 1);
IF @first_new_start IS NULL
BEGIN
    RAISERROR(N'ยังไม่มีกะแบบใหม่ — ทำขั้น 1 ก่อน', 16, 1);
    RETURN;
END;
-- ลบปฏิทินกะเดิมตั้งแต่กะแรกของรูปแบบใหม่ และตัดกะเดิมที่คร่อมเวลาเริ่มกะใหม่ให้จบพอดี
DELETE c FROM mfg.shift_calendar c JOIN @old o ON o.shift_code = c.shift_code WHERE c.shift_start >= @first_new_start;
UPDATE c SET shift_end = @first_new_start, note = N'ตัดจบเพราะเปลี่ยนรูปแบบกะ'
FROM   mfg.shift_calendar c JOIN @old o ON o.shift_code = c.shift_code
WHERE  c.shift_start < @first_new_start AND c.shift_end > @first_new_start;
DECLARE @to DATE = DATEFROMPARTS(YEAR(@change_date) + 1, 12, 31);
EXEC mfg.usp_build_shift_calendar @date_from = @change_date, @date_to = @to, @work_saturday = 1, @work_sunday = 0;

   หลังเปลี่ยนแล้ว ห้ามสร้างปฏิทินช่วงวันที่ก่อน @change_date อีก
   ===================================================================== */

PRINT N'03_reference_data.sql เสร็จ';
GO
SET NOEXEC OFF;
GO
