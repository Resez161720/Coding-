/* =====================================================================
   04_sample_data.sql  —  ข้อมูลตัวอย่าง 30 เครื่อง ย้อนหลัง 28 วัน (ถึงเวลาปัจจุบัน)

   ใช้เพื่อหัดสร้าง Dashboard ใน Tableau ก่อนต่อข้อมูลจริง
   >>> รันได้เฉพาะในฐานข้อมูลที่ชื่อมีคำว่า Demo (เช่น FactoryBI_Demo) และยังว่างอยู่ <<<
   ลำดับ: 01_schema.sql -> 02_views_and_procs.sql -> 03_reference_data.sql -> ไฟล์นี้

   สิ่งที่จำลองไว้ให้เห็นในตัวอย่าง:
     - 4 ไลน์ 30 เครื่อง ใช้งานจริง 24 เครื่อง (อีก 6 เครื่อง is_active = 0)
     - CNC-03 เป็นคอขวด: เสียบ่อยกว่าเครื่องอื่น และได้แผนเกือบเต็มกำลัง
     - PRS-02 ได้แผนเกินกำลังผลิตจริง (ต่อให้ไม่เสียก็ผลิตไม่ทัน)
     - PRS-05 เดินช้ากว่ามาตรฐาน (Performance ต่ำ)
     - INJ-04 ของเสียสูง (Quality ต่ำ)
     - การหยุดบางครั้งยังไม่ระบุสาเหตุ และบางครั้งคร่อมข้ามกะ
   ===================================================================== */

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb') OR DB_NAME() NOT LIKE N'%Demo%'
BEGIN
    RAISERROR(N'ข้อมูลตัวอย่างใส่ได้เฉพาะฐานข้อมูลที่ชื่อมีคำว่า Demo (เช่น FactoryBI_Demo) เพื่อไม่ให้ปนกับข้อมูลจริง', 16, 1);
    SET NOEXEC ON;
END
GO

IF EXISTS (SELECT 1 FROM mfg.machine) OR EXISTS (SELECT 1 FROM mfg.production_hour) OR EXISTS (SELECT 1 FROM mfg.downtime_event)
BEGIN
    RAISERROR(N'ฐานข้อมูลนี้มีข้อมูลอยู่แล้ว ไม่ใส่ข้อมูลตัวอย่างซ้ำ (ถ้าต้องการเริ่มใหม่ ให้ลบฐานข้อมูล Demo แล้วรันใหม่ทั้งชุด)', 16, 1);
    SET NOEXEC ON;
END
GO

SET NOCOUNT ON;

DECLARE @now   DATETIME2(0) = (SELECT now_local FROM mfg.v_now);
DECLARE @first DATE         = DATEADD(DAY, -27, CAST(@now AS DATE));
DECLARE @last  DATE         = DATEADD(DAY, 2, CAST(@now AS DATE));   -- มีแผนล่วงหน้า 2 วัน

IF NOT EXISTS (SELECT 1 FROM mfg.shift_calendar WHERE prod_date = @first)
   OR NOT EXISTS (SELECT 1 FROM mfg.shift_calendar WHERE prod_date = @last)
BEGIN
    EXEC mfg.usp_build_shift_calendar @date_from = @first, @date_to = @last;
END;

/* ---------- เครื่องจักร ---------- */
INSERT INTO mfg.machine (machine_id, machine_name, line_id, machine_type, is_active, is_bottleneck, sort_order)
SELECT  CONCAT(l.prefix, N'-', RIGHT(CONCAT(N'0', n.i), 2)),
        CONCAT(l.type_th, N' ', n.i),
        l.line_id,
        l.type_th,
        CASE WHEN n.i > l.active_count THEN 0 ELSE 1 END,
        CASE WHEN l.prefix = N'CNC' AND n.i = 3 THEN 1 ELSE 0 END,
        l.line_no * 100 + n.i
FROM (VALUES (1, N'INJ', N'L01-ฉีด',   N'เครื่องฉีดพลาสติก', 8, 6),
             (2, N'PRS', N'L02-ปั๊ม',   N'เครื่องปั๊ม',       8, 7),
             (3, N'CNC', N'L03-กลึง',  N'เครื่อง CNC',      8, 6),
             (4, N'ASY', N'L04-ประกอบ', N'สถานีประกอบ',     6, 5)
     ) l (line_no, prefix, line_id, type_th, machine_count, active_count)
CROSS APPLY (SELECT TOP (l.machine_count) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
             FROM sys.all_objects) n;

/* ---------- สินค้า และรอบเวลามาตรฐาน ---------- */
DECLARE @sku TABLE (prefix NVARCHAR(10), sku NVARCHAR(40), sku_no INT, product_name NVARCHAR(200), family NVARCHAR(100), base_ct DECIMAL(10,3));
INSERT INTO @sku VALUES
    (N'INJ', N'INJ-A01', 1, N'ฝาครอบพลาสติก A',  N'ชิ้นส่วนพลาสติก', 32.0),
    (N'INJ', N'INJ-A02', 2, N'ฝาครอบพลาสติก B',  N'ชิ้นส่วนพลาสติก', 38.0),
    (N'INJ', N'INJ-A03', 3, N'ขายึดพลาสติก',      N'ชิ้นส่วนพลาสติก', 26.0),
    (N'PRS', N'PRS-B01', 1, N'แผ่นยึดเหล็ก',       N'ชิ้นส่วนโลหะ',    7.5),
    (N'PRS', N'PRS-B02', 2, N'ขาตั้งเหล็ก',        N'ชิ้นส่วนโลหะ',    9.0),
    (N'PRS', N'PRS-B03', 3, N'แหวนรอง',           N'ชิ้นส่วนโลหะ',    6.0),
    (N'CNC', N'CNC-C01', 1, N'เพลา 20 มม.',        N'ชิ้นงานกลึง',     110.0),
    (N'CNC', N'CNC-C02', 2, N'บูชทองเหลือง',       N'ชิ้นงานกลึง',     95.0),
    (N'CNC', N'CNC-C03', 3, N'หน้าแปลน',          N'ชิ้นงานกลึง',     140.0),
    (N'ASY', N'ASY-D01', 1, N'ชุดประกอบ รุ่น 1',   N'งานประกอบ',       42.0),
    (N'ASY', N'ASY-D02', 2, N'ชุดประกอบ รุ่น 2',   N'งานประกอบ',       48.0),
    (N'ASY', N'ASY-D03', 3, N'ชุดประกอบ รุ่น 3',   N'งานประกอบ',       36.0);

INSERT INTO mfg.product (sku, product_name, product_family)
SELECT sku, product_name, family FROM @sku;

INSERT INTO mfg.std_cycle_time (machine_id, sku, ideal_ct_sec)
SELECT  m.machine_id, s.sku,
        CAST(s.base_ct * (0.95 + (ABS(CHECKSUM(CONCAT(m.machine_id, N'|', s.sku))) % 11) / 100.0) AS DECIMAL(10,3))
FROM    mfg.machine m
JOIN    @sku s ON s.prefix = LEFT(m.machine_id, 3);

/* ---------- แผนการผลิต ---------- */
INSERT INTO mfg.production_plan (prod_date, shift_code, machine_id, sku, plan_qty, source)
SELECT  c.prod_date, c.shift_code, m.machine_id, s.sku,
        CAST(FLOOR(c.planned_min * 60.0 / ct.ideal_ct_sec
                   * CASE WHEN m.machine_id IN (N'CNC-03', N'PRS-02') THEN 0.97 ELSE 0.78 END) AS INT),
        N'SAMPLE'
FROM    mfg.v_shift_calendar c
CROSS JOIN mfg.machine m
CROSS APPLY (SELECT ABS(CHECKSUM(CONCAT(m.machine_id, N'|', c.prod_date, N'|', c.shift_code))) AS h) hh
JOIN    @sku s ON s.prefix = LEFT(m.machine_id, 3) AND s.sku_no = hh.h % 3 + 1
JOIN    mfg.std_cycle_time ct ON ct.machine_id = m.machine_id AND ct.sku = s.sku
WHERE   c.prod_date BETWEEN @first AND @last
  AND   c.is_working = 1
  AND   m.is_active = 1
  AND   (hh.h / 7 % 100 >= 8 OR m.is_bottleneck = 1);      -- ประมาณ 8% ของกะ เครื่องไม่มีงาน

/* ---------- เครื่องหยุด ---------- */
DECLARE @reason TABLE (reason_code NVARCHAR(20), lo INT, hi INT, dmin INT, dmax INT);
INSERT INTO @reason VALUES
    (N'BD-MECH',  0, 17, 20, 100), (N'BD-ELEC', 18, 25, 15,  90), (N'BD-TOOL', 26, 29, 30, 110),
    (N'SETUP',   30, 49, 20,  60), (N'ADJUST',  50, 57,  5,  20), (N'MINOR',   58, 69,  3,  10),
    (N'MAT-WAIT',70, 79, 10,  60), (N'MAT-NG',  80, 83, 10,  40), (N'NO-OPR',  84, 88, 15,  60),
    (N'QC-HOLD', 89, 93, 10,  45), (N'UTILITY', 94, 95, 10,  30), (N'PM-PLAN', 96, 97, 60, 110),
    (N'NO-ORDER',98, 99, 60, 110);

-- แต่ละกะมีช่องให้เกิดการหยุดได้ 4 ช่อง (ช่องสุดท้ายอาจคร่อมไปกะถัดไป) ไม่ซ้อนกันเอง
INSERT INTO mfg.downtime_event (machine_id, start_ts, end_ts, reason_code, note, source)
SELECT  pp.machine_id,
        st.start_ts,
        DATEADD(MINUTE, r.dmin + hh.h3 % (r.dmax - r.dmin + 1), st.start_ts),
        CASE WHEN hh.h4 % 100 < 7 THEN NULL ELSE r.reason_code END,
        NULL,
        N'SAMPLE'
FROM    (SELECT DISTINCT machine_id, prod_date, shift_code FROM mfg.production_plan) pp
JOIN    mfg.shift_calendar c ON c.prod_date = pp.prod_date AND c.shift_code = pp.shift_code
JOIN    mfg.machine m        ON m.machine_id = pp.machine_id
CROSS JOIN (VALUES (0, 90, 75), (1, 270, 55), (2, 450, 35), (3, 630, 20)) k (k, offset_min, prob)
CROSS APPLY (SELECT ABS(CHECKSUM(CONCAT(pp.machine_id, N'|', pp.prod_date, N'|', pp.shift_code, N'|', k.k, N'|a'))) AS h1,
                    ABS(CHECKSUM(CONCAT(pp.machine_id, N'|', pp.prod_date, N'|', pp.shift_code, N'|', k.k, N'|b'))) AS h2,
                    ABS(CHECKSUM(CONCAT(pp.machine_id, N'|', pp.prod_date, N'|', pp.shift_code, N'|', k.k, N'|c'))) AS h3,
                    ABS(CHECKSUM(CONCAT(pp.machine_id, N'|', pp.prod_date, N'|', pp.shift_code, N'|', k.k, N'|d'))) AS h4) hh
CROSS APPLY (SELECT CASE WHEN m.is_bottleneck = 1 AND hh.h2 % 100 < 40 THEN 5   -- คอขวด: เสียบ่อย
                         ELSE hh.h2 % 100 END AS pick) p
JOIN    @reason r ON p.pick BETWEEN r.lo AND r.hi
CROSS APPLY (SELECT DATEADD(MINUTE, k.offset_min + hh.h1 % 60, c.shift_start) AS start_ts) st
WHERE   hh.h1 / 3 % 100 < k.prob + CASE WHEN m.is_bottleneck = 1 THEN 20 ELSE 0 END
  AND   st.start_ts < @now;

-- การหยุดที่ยังไม่จบ ณ ตอนนี้ -> เปิดค้างไว้ (end_ts ว่าง) เหมือนข้อมูลจริง
UPDATE mfg.downtime_event SET end_ts = NULL WHERE end_ts > @now;

/* ---------- ยอดผลิตรายชั่วโมง (เฉพาะชั่วโมงที่จบแล้ว) ---------- */
WITH slot AS (
    SELECT  pp.machine_id, pp.sku, ct.ideal_ct_sec, h.prod_date, h.shift_code, h.hour_start, h.hour_end,
            bo.overlap_sec AS break_sec
    FROM    mfg.production_plan pp
    JOIN    mfg.std_cycle_time ct ON ct.machine_id = pp.machine_id AND ct.sku = pp.sku
    JOIN    mfg.v_shift_hour h    ON h.prod_date = pp.prod_date AND h.shift_code = pp.shift_code
    CROSS APPLY mfg.tvf_break_overlap_sec(h.prod_date, h.shift_code, h.hour_start, h.hour_end) bo
    WHERE   h.hour_end <= @now
),
dt AS (
    SELECT  s.machine_id, s.hour_start,
            SUM(DATEDIFF(SECOND,
                CASE WHEN e.start_ts > s.hour_start THEN e.start_ts ELSE s.hour_start END,
                CASE WHEN ISNULL(e.end_ts, @now) < s.hour_end THEN ISNULL(e.end_ts, @now) ELSE s.hour_end END)) AS down_sec
    FROM    slot s
    JOIN    mfg.downtime_event e ON e.machine_id = s.machine_id
                                AND e.start_ts < s.hour_end AND ISNULL(e.end_ts, @now) > s.hour_start
    GROUP BY s.machine_id, s.hour_start
)
INSERT INTO mfg.production_hour (machine_id, hour_start, sku, total_qty, good_qty, source)
SELECT  s.machine_id, s.hour_start, s.sku, q.total_qty,
        q.total_qty - CAST(CEILING(q.total_qty * sr.scrap_rate) AS INT),
        N'SAMPLE'
FROM    slot s
LEFT JOIN dt ON dt.machine_id = s.machine_id AND dt.hour_start = s.hour_start
CROSS APPLY (SELECT ABS(CHECKSUM(CONCAT(s.machine_id, N'|', s.hour_start, N'|q'))) AS h) hh
CROSS APPLY (SELECT CASE WHEN 3600 - s.break_sec - ISNULL(dt.down_sec, 0) > 0
                         THEN 3600 - s.break_sec - ISNULL(dt.down_sec, 0) ELSE 0 END AS run_sec,
                    CASE WHEN s.machine_id = N'PRS-05' THEN 0.70 ELSE 0.82 + (hh.h % 14) / 100.0 END AS speed) x
CROSS APPLY (SELECT CAST(FLOOR(x.run_sec * x.speed / s.ideal_ct_sec) AS INT) AS total_qty) q
CROSS APPLY (SELECT CASE WHEN s.machine_id = N'INJ-04' THEN (60 + hh.h / 7 % 30) / 1000.0
                         ELSE (5 + hh.h / 7 % 30) / 1000.0 END AS scrap_rate) sr;

/* ---------- สรุป ---------- */
SELECT  N'เครื่องจักร' AS item, COUNT(*) AS row_count FROM mfg.machine
UNION ALL SELECT N'แผนการผลิต', COUNT(*) FROM mfg.production_plan
UNION ALL SELECT N'การหยุด', COUNT(*) FROM mfg.downtime_event
UNION ALL SELECT N'ยอดผลิตรายชั่วโมง', COUNT(*) FROM mfg.production_hour;

PRINT N'04_sample_data.sql เสร็จ: ลองดู SELECT TOP 20 * FROM rpt.v_oee_shift ORDER BY shift_start DESC;';
GO
SET NOEXEC OFF;
GO
