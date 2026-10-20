/* =====================================================================
   02_views_and_procs.sql  —  view สำหรับ Tableau (schema rpt) และ procedure ช่วยงาน

   วิธีรัน: เลือกฐานข้อมูลเดียวกับที่รัน 01_schema.sql แล้วกด Execute
   รันซ้ำได้ทุกเมื่อ (ใช้ CREATE OR ALTER) ไม่กระทบข้อมูล

   view ที่ Tableau ใช้ (ให้สิทธิ์ tableau_reader อ่านเฉพาะ schema rpt):
     rpt.v_machine               ข้อมูลเครื่องจักร
     rpt.v_oee_shift             OEE ต่อ เครื่อง x กะ  (Dashboard OEE / คอขวด)
     rpt.v_plan_vs_actual_hour   แผนเทียบผลิตจริง รายชั่วโมง (Dashboard แผน vs จริง / จอทีวี)
     rpt.v_plan_vs_actual_sku    แผนเทียบผลิตจริง ต่อ เครื่อง x กะ x สินค้า
     rpt.v_downtime_segment      เวลาเครื่องหยุด ตัดตามกะ หักเวลาพักแล้ว (Dashboard Pareto)
     rpt.v_production_hour       ยอดผลิตรายชั่วโมงแบบละเอียด
     rpt.v_data_quality          รายการปัญหาคุณภาพข้อมูล
   ===================================================================== */

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
BEGIN
    RAISERROR(N'กรุณาเลือกฐานข้อมูลของโรงงาน (เช่น FactoryBI) ก่อนรันสคริปต์นี้', 16, 1);
    SET NOEXEC ON;
END
GO

/* =====================================================================
   ส่วนที่ 1: ตัวช่วยภายใน (schema mfg)
   ===================================================================== */

-- เวลาปัจจุบันตามเวลาไทย ไม่ว่าเครื่อง SQL Server จะตั้ง time zone ไว้แบบไหน
CREATE OR ALTER VIEW mfg.v_now
AS
SELECT CAST(SWITCHOFFSET(SYSDATETIMEOFFSET(), '+07:00') AS DATETIME2(0)) AS now_local;
GO

-- ช่วงเวลาพักจริงของแต่ละกะในแต่ละวัน
CREATE OR ALTER VIEW mfg.v_shift_break
AS
SELECT  c.prod_date,
        c.shift_code,
        b.break_no,
        DATEADD(MINUTE, b.offset_min, c.shift_start) AS break_start,
        CASE WHEN DATEADD(MINUTE, b.offset_min + b.break_min, c.shift_start) > c.shift_end
             THEN c.shift_end
             ELSE DATEADD(MINUTE, b.offset_min + b.break_min, c.shift_start) END AS break_end
FROM    mfg.shift_calendar c
JOIN    mfg.shift_break_definition b ON b.shift_code = c.shift_code
WHERE   DATEADD(MINUTE, b.offset_min, c.shift_start) < c.shift_end;
GO

-- จำนวนวินาทีที่ช่วง [@from, @to) ทับกับเวลาพักของกะ
CREATE OR ALTER FUNCTION mfg.tvf_break_overlap_sec
(
    @prod_date  DATE,
    @shift_code NVARCHAR(10),
    @from       DATETIME2(0),
    @to         DATETIME2(0)
)
RETURNS TABLE
AS
RETURN
SELECT ISNULL(SUM(DATEDIFF(SECOND,
            CASE WHEN b.break_start > @from THEN b.break_start ELSE @from END,
            CASE WHEN b.break_end   < @to   THEN b.break_end   ELSE @to   END)), 0) AS overlap_sec
FROM   mfg.v_shift_break b
WHERE  b.prod_date  = @prod_date
  AND  b.shift_code = @shift_code
  AND  @to > @from
  AND  b.break_start < @to
  AND  b.break_end   > @from;
GO

-- ปฏิทินกะ + นาทีที่วางแผนผลิตได้ (หักเวลาพักแล้ว)
CREATE OR ALTER VIEW mfg.v_shift_calendar
AS
SELECT  c.prod_date,
        c.shift_code,
        d.shift_name_th,
        d.sort_order AS shift_sort,
        c.shift_start,
        c.shift_end,
        c.is_working,
        DATEDIFF(MINUTE, c.shift_start, c.shift_end)                                     AS scheduled_min,
        CAST(bo.overlap_sec / 60.0 AS DECIMAL(10,2))                                     AS break_min,
        CAST((DATEDIFF(SECOND, c.shift_start, c.shift_end) - bo.overlap_sec) / 60.0 AS DECIMAL(10,2)) AS planned_min
FROM    mfg.shift_calendar c
JOIN    mfg.shift_definition d ON d.shift_code = c.shift_code
CROSS APPLY mfg.tvf_break_overlap_sec(c.prod_date, c.shift_code, c.shift_start, c.shift_end) bo;
GO

-- ช่องรายชั่วโมงของแต่ละกะ (กะ 12 ชม. = 12 ช่อง) พร้อมนาทีที่ผลิตได้ในช่องนั้น
CREATE OR ALTER VIEW mfg.v_shift_hour
AS
SELECT  c.prod_date,
        c.shift_code,
        s.slot_no + 1 AS slot_no,
        h.hour_start,
        h.hour_end,
        CAST((3600 - bo.overlap_sec) / 60.0 AS DECIMAL(10,2)) AS planned_min
FROM    mfg.shift_calendar c
CROSS JOIN (VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),
                   (12),(13),(14),(15),(16),(17),(18),(19),(20),(21),(22),(23)) s (slot_no)
CROSS APPLY (SELECT DATEADD(HOUR, s.slot_no,     c.shift_start) AS hour_start,
                    DATEADD(HOUR, s.slot_no + 1, c.shift_start) AS hour_end) h
CROSS APPLY mfg.tvf_break_overlap_sec(c.prod_date, c.shift_code, h.hour_start, h.hour_end) bo
WHERE   h.hour_end <= c.shift_end;
GO

-- กะล่าสุดนับย้อนหลัง: 0 = กะที่กำลังเดินอยู่ (หรือกะล่าสุดที่เริ่มไปแล้ว), 1 = กะก่อนหน้า, ...
-- นับเฉพาะกะทำงาน (is_working = 1) หรือกะที่มีแผนผลิต ย้อนหลังไม่เกิน 62 วัน
-- ใช้ใน Tableau กรอง "กะปัจจุบัน" / "กะที่แล้ว" ได้ตรงเสมอ แม้กะดึกจะข้ามเที่ยงคืน
CREATE OR ALTER VIEW mfg.v_shift_recent
AS
SELECT  c.prod_date,
        c.shift_code,
        ROW_NUMBER() OVER (ORDER BY c.shift_start DESC) - 1 AS shifts_ago
FROM    mfg.shift_calendar c
CROSS JOIN mfg.v_now n
WHERE   c.shift_start <= n.now_local
  AND   c.shift_start >  DATEADD(DAY, -62, n.now_local)
  AND   (c.is_working = 1
         OR EXISTS (SELECT 1 FROM mfg.production_plan p
                    WHERE p.prod_date = c.prod_date AND p.shift_code = c.shift_code AND p.plan_qty > 0));
GO

-- เครื่อง x กะ ที่ "มีงาน" = มีแผน หรือ มียอดผลิตจริง
-- เครื่องที่ไม่มีแผนและไม่ได้ผลิต จะไม่ถูกนับเวลาใน OEE (ถือว่าไม่ได้วางแผนให้เดิน)
CREATE OR ALTER VIEW mfg.v_machine_shift_scheduled
AS
SELECT  pp.machine_id, pp.prod_date, pp.shift_code
FROM    mfg.production_plan pp
WHERE   pp.plan_qty > 0
UNION
SELECT  p.machine_id, c.prod_date, c.shift_code
FROM    mfg.production_hour p
JOIN    mfg.shift_calendar c ON p.hour_start >= c.shift_start AND p.hour_start < c.shift_end
WHERE   p.total_qty > 0;
GO

/* =====================================================================
   ส่วนที่ 2: view สำหรับ Tableau (schema rpt)
   ===================================================================== */

CREATE OR ALTER VIEW rpt.v_machine
AS
SELECT  machine_id, machine_name, line_id, machine_type, is_active, is_bottleneck, sort_order
FROM    mfg.machine;
GO

/* เวลาเครื่องหยุด แยกเป็นชิ้นตามกะ
   - การหยุดที่คร่อมกะ จะถูกแบ่งเป็นหลายแถว (แถวละกะ)
   - downtime_min = เวลาหยุดหลังหักส่วนที่ทับเวลาพักแล้ว
   - การหยุดที่ยังไม่จบ (end_ts ว่าง) นับถึงเวลาปัจจุบัน
   - ยังไม่ระบุสาเหตุ -> reason_code = 'UNCODED' และนับเป็นความสูญเสีย */
CREATE OR ALTER VIEW rpt.v_downtime_segment
AS
SELECT  e.event_id,
        e.machine_id,
        c.prod_date,
        c.shift_code,
        s.seg_start,
        s.seg_end,
        CAST((DATEDIFF(SECOND, s.seg_start, s.seg_end) - bo.overlap_sec) / 60.0 AS DECIMAL(10,2)) AS downtime_min,
        CAST(bo.overlap_sec / 60.0 AS DECIMAL(10,2))                                              AS break_overlap_min,
        CASE WHEN e.end_ts IS NULL THEN 1 ELSE 0 END                                              AS is_ongoing,
        CASE WHEN n.now_local >= c.shift_start AND n.now_local < c.shift_end THEN 1 ELSE 0 END    AS is_current_shift,
        sr.shifts_ago,
        ISNULL(e.reason_code, N'UNCODED')                                                         AS reason_code,
        ISNULL(r.reason_name_th, N'ยังไม่ระบุสาเหตุ')                                              AS reason_name_th,
        ISNULL(r.reason_name_en, N'Uncoded')                                                      AS reason_name_en,
        ISNULL(r.loss_category, N'UNCODED')                                                       AS loss_category,
        CASE WHEN r.loss_category = N'PLANNED' THEN 1 ELSE 0 END                                  AS is_planned_stop,
        r.responsible_dept,
        e.start_ts                                                                                AS event_start_ts,
        e.end_ts                                                                                  AS event_end_ts,
        CAST(DATEDIFF(SECOND, e.start_ts, x.eff_end) / 60.0 AS DECIMAL(10,2))                     AS event_total_min,
        e.note
FROM    mfg.downtime_event e
CROSS JOIN mfg.v_now n
CROSS APPLY (SELECT ISNULL(e.end_ts, n.now_local) AS eff_end) x
JOIN    mfg.shift_calendar c ON e.start_ts < c.shift_end AND x.eff_end > c.shift_start
CROSS APPLY (SELECT CASE WHEN e.start_ts > c.shift_start THEN e.start_ts ELSE c.shift_start END AS seg_start,
                    CASE WHEN x.eff_end  < c.shift_end   THEN x.eff_end  ELSE c.shift_end   END AS seg_end) s
CROSS APPLY mfg.tvf_break_overlap_sec(c.prod_date, c.shift_code, s.seg_start, s.seg_end) bo
LEFT JOIN mfg.downtime_reason r ON r.reason_code = e.reason_code
LEFT JOIN mfg.v_shift_recent sr ON sr.prod_date = c.prod_date AND sr.shift_code = c.shift_code
WHERE   e.start_ts < n.now_local;
GO

/* OEE ต่อ เครื่อง x วันผลิต x กะ
   เก็บเป็น "นาที" และ "จำนวนชิ้น" ไว้ให้ Tableau หารเอง (ห้ามเฉลี่ย % ข้ามแถว)
   - shift_planned_min      นาทีตามตารางกะที่ผ่านไปแล้ว หักเวลาพัก (กะปัจจุบันนับถึงตอนนี้)
   - planned_stop_min       หยุดตามแผน (PM, ไม่มีออร์เดอร์) -> ไม่นับเป็นความสูญเสีย
   - planned_production_min เวลาที่ตั้งใจจะผลิต = ตัวหารของ Availability และ OEE
   - unplanned_downtime_min เวลาหยุดที่เป็นความสูญเสีย (รวมเปลี่ยนรุ่น และที่ยังไม่ระบุสาเหตุ)
   - run_min                เวลาเดินเครื่องจริง
   - ideal_run_min          ชิ้นทั้งหมด x รอบเวลามาตรฐาน
   - good_ideal_min         ชิ้นดี x รอบเวลามาตรฐาน
   สูตรใน Tableau:
     Availability = SUM(run_min) / SUM(planned_production_min)
     Performance  = SUM(ideal_run_min) / SUM(run_min)
     Quality      = SUM(good_ideal_min) / SUM(ideal_run_min)
     OEE          = SUM(good_ideal_min) / SUM(planned_production_min)   (= A x P x Q พอดี) */
CREATE OR ALTER VIEW rpt.v_oee_shift
AS
WITH prod AS (
    SELECT  p.machine_id, c.prod_date, c.shift_code,
            SUM(p.total_qty)                                               AS total_qty,
            SUM(p.good_qty)                                                AS good_qty,
            SUM(p.total_qty * ct.ideal_ct_sec)                             AS ideal_run_sec,
            SUM(p.good_qty  * ct.ideal_ct_sec)                             AS good_ideal_sec,
            SUM(CASE WHEN ct.ideal_ct_sec IS NULL THEN p.total_qty ELSE 0 END) AS qty_missing_ct
    FROM    mfg.production_hour p
    JOIN    mfg.shift_calendar c ON p.hour_start >= c.shift_start AND p.hour_start < c.shift_end
    LEFT JOIN mfg.std_cycle_time ct ON ct.machine_id = p.machine_id AND ct.sku = p.sku
    GROUP BY p.machine_id, c.prod_date, c.shift_code
),
pl AS (
    SELECT  pp.machine_id, pp.prod_date, pp.shift_code,
            SUM(pp.plan_qty)                                                AS plan_qty,
            SUM(pp.plan_qty * ct.ideal_ct_sec)                              AS plan_ideal_sec,
            SUM(CASE WHEN ct.ideal_ct_sec IS NULL THEN pp.plan_qty ELSE 0 END) AS plan_qty_missing_ct
    FROM    mfg.production_plan pp
    LEFT JOIN mfg.std_cycle_time ct ON ct.machine_id = pp.machine_id AND ct.sku = pp.sku
    GROUP BY pp.machine_id, pp.prod_date, pp.shift_code
),
dt AS (
    SELECT  machine_id, prod_date, shift_code,
            SUM(CASE WHEN is_planned_stop = 1 THEN downtime_min ELSE 0 END)          AS planned_stop_min,
            SUM(CASE WHEN is_planned_stop = 0 THEN downtime_min ELSE 0 END)          AS unplanned_min,
            SUM(CASE WHEN loss_category = N'UNCODED' THEN downtime_min ELSE 0 END)   AS uncoded_min,
            COUNT(DISTINCT CASE WHEN is_planned_stop = 0 THEN event_id END)         AS unplanned_stop_count,
            COUNT(DISTINCT CASE WHEN loss_category = N'BREAKDOWN' THEN event_id END) AS breakdown_count,
            SUM(CASE WHEN loss_category = N'BREAKDOWN' THEN downtime_min ELSE 0 END) AS breakdown_min
    FROM    rpt.v_downtime_segment
    GROUP BY machine_id, prod_date, shift_code
)
SELECT  k.machine_id,
        c.prod_date,
        c.shift_code,
        c.shift_name_th,
        c.shift_start,
        c.shift_end,
        CASE WHEN n.now_local >= c.shift_end THEN 1 ELSE 0 END                AS is_shift_closed,
        CASE WHEN n.now_local < c.shift_end THEN 1 ELSE 0 END                 AS is_current_shift,
        sr.shifts_ago,
        c.planned_min                                                         AS full_shift_planned_min,
        e.elapsed_planned_min                                                 AS shift_planned_min,
        a.planned_stop_min,
        a.planned_production_min,
        b.unplanned_downtime_min,
        CAST(a.planned_production_min - b.unplanned_downtime_min AS DECIMAL(10,2)) AS run_min,
        ISNULL(pr.total_qty, 0)                                               AS total_qty,
        ISNULL(pr.good_qty, 0)                                                AS good_qty,
        ISNULL(pr.total_qty, 0) - ISNULL(pr.good_qty, 0)                      AS scrap_qty,
        CAST(ISNULL(pr.ideal_run_sec, 0)  / 60.0 AS DECIMAL(12,2))            AS ideal_run_min,
        CAST(ISNULL(pr.good_ideal_sec, 0) / 60.0 AS DECIMAL(12,2))            AS good_ideal_min,
        ISNULL(pr.qty_missing_ct, 0)                                          AS qty_missing_ct,
        ISNULL(pl.plan_qty, 0)                                                AS plan_qty,
        CAST(ISNULL(pl.plan_ideal_sec, 0) / 60.0 AS DECIMAL(12,2))            AS plan_ideal_min,
        ISNULL(pl.plan_qty_missing_ct, 0)                                     AS plan_qty_missing_ct,
        CAST(ISNULL(dt.uncoded_min, 0) AS DECIMAL(10,2))                      AS uncoded_downtime_min,
        ISNULL(dt.unplanned_stop_count, 0)                                    AS unplanned_stop_count,
        ISNULL(dt.breakdown_count, 0)                                         AS breakdown_count,
        CAST(ISNULL(dt.breakdown_min, 0) AS DECIMAL(10,2))                    AS breakdown_min
FROM    mfg.v_machine_shift_scheduled k
JOIN    mfg.v_shift_calendar c ON c.prod_date = k.prod_date AND c.shift_code = k.shift_code
CROSS JOIN mfg.v_now n
CROSS APPLY (SELECT CASE WHEN n.now_local < c.shift_end THEN n.now_local ELSE c.shift_end END AS elapsed_end) ee
CROSS APPLY mfg.tvf_break_overlap_sec(c.prod_date, c.shift_code, c.shift_start, ee.elapsed_end) bo
CROSS APPLY (SELECT CAST((DATEDIFF(SECOND, c.shift_start, ee.elapsed_end) - bo.overlap_sec) / 60.0 AS DECIMAL(10,2)) AS elapsed_planned_min) e
LEFT JOIN prod pr ON pr.machine_id = k.machine_id AND pr.prod_date = k.prod_date AND pr.shift_code = k.shift_code
LEFT JOIN pl      ON pl.machine_id = k.machine_id AND pl.prod_date = k.prod_date AND pl.shift_code = k.shift_code
LEFT JOIN dt      ON dt.machine_id = k.machine_id AND dt.prod_date = k.prod_date AND dt.shift_code = k.shift_code
LEFT JOIN mfg.v_shift_recent sr ON sr.prod_date = k.prod_date AND sr.shift_code = k.shift_code
CROSS APPLY (SELECT CAST(CASE WHEN ISNULL(dt.planned_stop_min, 0) > e.elapsed_planned_min
                              THEN e.elapsed_planned_min ELSE ISNULL(dt.planned_stop_min, 0) END AS DECIMAL(10,2)) AS planned_stop_min) ps
CROSS APPLY (SELECT ps.planned_stop_min,
                    CAST(e.elapsed_planned_min - ps.planned_stop_min AS DECIMAL(10,2)) AS planned_production_min) a
CROSS APPLY (SELECT CAST(CASE WHEN ISNULL(dt.unplanned_min, 0) > a.planned_production_min
                              THEN a.planned_production_min ELSE ISNULL(dt.unplanned_min, 0) END AS DECIMAL(10,2)) AS unplanned_downtime_min) b
WHERE   c.shift_start < n.now_local;
GO

/* แผนเทียบผลิตจริง รายชั่วโมง (เฉพาะกะที่เริ่มแล้ว และเครื่องที่มีงาน)
   - plan_qty            แผนของชั่วโมงนั้น (กระจายแผนทั้งกะตามนาทีที่ผลิตได้ ชั่วโมงที่มีพักจะได้แผนน้อยลง)
   - plan_qty_elapsed    แผนที่ "ควรทำได้ถึงตอนนี้" ในชั่วโมงนั้น
   - actual_good_qty     ของดีที่ผลิตได้ (ชั่วโมงที่ยังไม่ถึงจะเป็นค่าว่าง กราฟจะได้หยุดที่ปัจจุบัน)
   - remaining_planned_min  นาทีที่ยังเหลือให้ผลิตในชั่วโมงนั้น (ใช้คำนวณ "ต้องผลิตชั่วโมงละเท่าไรถึงจะทัน") */
CREATE OR ALTER VIEW rpt.v_plan_vs_actual_hour
AS
WITH pl AS (
    SELECT  machine_id, prod_date, shift_code, SUM(plan_qty) AS plan_qty
    FROM    mfg.production_plan
    GROUP BY machine_id, prod_date, shift_code
),
act AS (
    SELECT  machine_id, hour_start, SUM(total_qty) AS total_qty, SUM(good_qty) AS good_qty
    FROM    mfg.production_hour
    GROUP BY machine_id, hour_start
)
SELECT  k.machine_id,
        h.prod_date,
        h.shift_code,
        c.shift_name_th,
        h.slot_no,
        h.hour_start,
        h.hour_end,
        h.planned_min                                                                       AS slot_planned_min,
        CAST(ISNULL(pl.plan_qty, 0) * h.planned_min / NULLIF(c.planned_min, 0) AS DECIMAL(12,2)) AS plan_qty,
        CAST(ISNULL(pl.plan_qty, 0) * (h.planned_min - r.remaining_planned_min)
             / NULLIF(c.planned_min, 0) AS DECIMAL(12,2))                                   AS plan_qty_elapsed,
        CASE WHEN h.hour_start < n.now_local THEN ISNULL(a.good_qty, 0)  END                AS actual_good_qty,
        CASE WHEN h.hour_start < n.now_local THEN ISNULL(a.total_qty, 0) END                AS actual_total_qty,
        r.remaining_planned_min,
        CASE WHEN h.hour_end  <= n.now_local THEN N'DONE'
             WHEN h.hour_start <= n.now_local THEN N'CURRENT'
             ELSE N'FUTURE' END                                                             AS hour_status,
        CASE WHEN n.now_local >= c.shift_end THEN 1 ELSE 0 END                              AS is_shift_closed,
        CASE WHEN n.now_local < c.shift_end THEN 1 ELSE 0 END                               AS is_current_shift,
        sr.shifts_ago
FROM    mfg.v_machine_shift_scheduled k
JOIN    mfg.v_shift_calendar c ON c.prod_date = k.prod_date AND c.shift_code = k.shift_code
JOIN    mfg.v_shift_hour h     ON h.prod_date = k.prod_date AND h.shift_code = k.shift_code
CROSS JOIN mfg.v_now n
CROSS APPLY (SELECT CASE WHEN n.now_local > h.hour_start THEN n.now_local ELSE h.hour_start END AS rem_from) rf
CROSS APPLY (SELECT CASE WHEN rf.rem_from > h.hour_end THEN rf.rem_from ELSE h.hour_end END AS rem_to) rt
CROSS APPLY mfg.tvf_break_overlap_sec(h.prod_date, h.shift_code, rf.rem_from, rt.rem_to) bo
CROSS APPLY (SELECT CAST((DATEDIFF(SECOND, rf.rem_from, rt.rem_to) - bo.overlap_sec) / 60.0 AS DECIMAL(10,2)) AS remaining_planned_min) r
LEFT JOIN pl  ON pl.machine_id = k.machine_id AND pl.prod_date = k.prod_date AND pl.shift_code = k.shift_code
LEFT JOIN act a ON a.machine_id = k.machine_id AND a.hour_start = h.hour_start
LEFT JOIN mfg.v_shift_recent sr ON sr.prod_date = k.prod_date AND sr.shift_code = k.shift_code
WHERE   c.shift_start <= n.now_local;
GO

/* แผนเทียบผลิตจริง ต่อ เครื่อง x กะ x สินค้า (รวมกะในอนาคตที่มีแผนแล้วด้วย)
   adherence_qty = ของดีที่ผลิตตรงตามแผน (ผลิตเกินแผนของสินค้าหนึ่ง ไม่ชดเชยสินค้าอื่นที่ขาด)
   Schedule Adherence % ใน Tableau = SUM(adherence_qty) / SUM(plan_qty) */
CREATE OR ALTER VIEW rpt.v_plan_vs_actual_sku
AS
WITH pl AS (
    SELECT  machine_id, prod_date, shift_code, sku, SUM(plan_qty) AS plan_qty
    FROM    mfg.production_plan
    GROUP BY machine_id, prod_date, shift_code, sku
),
act AS (
    SELECT  p.machine_id, c.prod_date, c.shift_code, p.sku,
            SUM(p.total_qty) AS total_qty, SUM(p.good_qty) AS good_qty
    FROM    mfg.production_hour p
    JOIN    mfg.shift_calendar c ON p.hour_start >= c.shift_start AND p.hour_start < c.shift_end
    GROUP BY p.machine_id, c.prod_date, c.shift_code, p.sku
),
j AS (
    SELECT  COALESCE(pl.machine_id, act.machine_id) AS machine_id,
            COALESCE(pl.prod_date,  act.prod_date)  AS prod_date,
            COALESCE(pl.shift_code, act.shift_code) AS shift_code,
            COALESCE(pl.sku,        act.sku)        AS sku,
            ISNULL(pl.plan_qty, 0)   AS plan_qty,
            ISNULL(act.total_qty, 0) AS total_qty,
            ISNULL(act.good_qty, 0)  AS good_qty
    FROM    pl
    FULL OUTER JOIN act ON act.machine_id = pl.machine_id AND act.prod_date = pl.prod_date
                       AND act.shift_code = pl.shift_code AND act.sku = pl.sku
)
SELECT  j.machine_id,
        j.prod_date,
        j.shift_code,
        c.shift_name_th,
        c.shift_start,
        j.sku,
        pr.product_name,
        j.plan_qty,
        j.total_qty,
        j.good_qty,
        j.total_qty - j.good_qty                                         AS scrap_qty,
        CASE WHEN j.good_qty < j.plan_qty THEN j.good_qty ELSE j.plan_qty END AS adherence_qty,
        ct.ideal_ct_sec,
        CAST(j.plan_qty * ct.ideal_ct_sec / 60.0 AS DECIMAL(12,2))       AS plan_ideal_min,
        CASE WHEN n.now_local >= c.shift_end   THEN N'CLOSED'
             WHEN n.now_local >= c.shift_start THEN N'RUNNING'
             ELSE N'FUTURE' END                                          AS shift_status,
        sr.shifts_ago
FROM    j
JOIN    mfg.v_shift_calendar c ON c.prod_date = j.prod_date AND c.shift_code = j.shift_code
CROSS JOIN mfg.v_now n
LEFT JOIN mfg.product pr        ON pr.sku = j.sku
LEFT JOIN mfg.std_cycle_time ct ON ct.machine_id = j.machine_id AND ct.sku = j.sku
LEFT JOIN mfg.v_shift_recent sr ON sr.prod_date = j.prod_date AND sr.shift_code = j.shift_code;
GO

-- ยอดผลิตรายชั่วโมงแบบละเอียด (ต่อสินค้า)
CREATE OR ALTER VIEW rpt.v_production_hour
AS
SELECT  p.machine_id,
        c.prod_date,
        c.shift_code,
        p.hour_start,
        p.sku,
        pr.product_name,
        pr.product_family,
        p.total_qty,
        p.good_qty,
        p.total_qty - p.good_qty                                    AS scrap_qty,
        ct.ideal_ct_sec,
        CAST(p.total_qty * ct.ideal_ct_sec / 60.0 AS DECIMAL(12,2)) AS ideal_run_min,
        CAST(p.good_qty  * ct.ideal_ct_sec / 60.0 AS DECIMAL(12,2)) AS good_ideal_min,
        p.source,
        p.updated_at
FROM    mfg.production_hour p
LEFT JOIN mfg.shift_calendar c  ON p.hour_start >= c.shift_start AND p.hour_start < c.shift_end
LEFT JOIN mfg.product pr        ON pr.sku = p.sku
LEFT JOIN mfg.std_cycle_time ct ON ct.machine_id = p.machine_id AND ct.sku = p.sku;
GO

/* รายการปัญหาคุณภาพข้อมูล (ยิ่งน้อยยิ่งดี) — ใช้ทำหน้า Data Health ใน Tableau
   หรือรันดูใน SSMS:  SELECT * FROM rpt.v_data_quality ORDER BY severity, check_code; */
CREATE OR ALTER VIEW rpt.v_data_quality
AS
-- 1) การหยุดที่ยังไม่ปิดนานเกิน 12 ชั่วโมง (มักเป็นลืมกดจบ)
SELECT  N'1-HIGH' AS severity, N'OPEN_STOP_TOO_LONG' AS check_code,
        N'เครื่องหยุดค้างเกิน 12 ชม. (ลืมปิดหรือไม่)' AS check_name_th,
        e.machine_id, e.start_ts AS ref_time,
        CONCAT(N'event_id=', e.event_id, N' เริ่ม ', CONVERT(NVARCHAR(16), e.start_ts, 120)) AS detail
FROM    mfg.downtime_event e CROSS JOIN mfg.v_now n
WHERE   e.end_ts IS NULL AND e.start_ts < DATEADD(HOUR, -12, n.now_local)
UNION ALL
-- 2) การหยุดซ้อนกันในเครื่องเดียวกัน (ทำให้นับเวลาหยุดเกินจริง) ตรวจย้อนหลัง 60 วัน
SELECT  N'1-HIGH', N'OVERLAPPING_STOPS', N'บันทึกเครื่องหยุดซ้อนทับกัน',
        a.machine_id, a.start_ts,
        CONCAT(N'event_id=', a.event_id, N' ซ้อนกับ event_id=', b.event_id)
FROM    mfg.downtime_event a
CROSS JOIN mfg.v_now n
JOIN    mfg.downtime_event b
        ON  b.machine_id = a.machine_id
        AND b.event_id   > a.event_id
        AND b.start_ts   < ISNULL(a.end_ts, n.now_local)
        AND a.start_ts   < ISNULL(b.end_ts, n.now_local)
WHERE   a.start_ts >= DATEADD(DAY, -60, n.now_local)
UNION ALL
-- 3) ผลิตสินค้าที่ยังไม่มีรอบเวลามาตรฐาน (OEE ของเครื่องนั้นจะต่ำเกินจริง)
SELECT  N'1-HIGH', N'MISSING_CYCLE_TIME', N'ไม่มีรอบเวลามาตรฐานของสินค้านี้บนเครื่องนี้',
        x.machine_id, MAX(x.ref_time),
        CONCAT(N'sku=', x.sku)
FROM (
    SELECT p.machine_id, p.sku, p.hour_start AS ref_time FROM mfg.production_hour p
    UNION ALL
    SELECT pp.machine_id, pp.sku, CAST(pp.prod_date AS DATETIME2(0)) FROM mfg.production_plan pp
) x
LEFT JOIN mfg.std_cycle_time ct ON ct.machine_id = x.machine_id AND ct.sku = x.sku
WHERE   ct.ideal_ct_sec IS NULL
GROUP BY x.machine_id, x.sku
UNION ALL
-- 4) ยอดผลิตที่ไม่ตรงกับกะใด ๆ (ปฏิทินกะไม่ครอบคลุม จะไม่ถูกนับใน OEE)
SELECT  N'1-HIGH', N'PRODUCTION_OUTSIDE_SHIFT', N'ยอดผลิตอยู่นอกเวลากะ / ยังไม่ได้สร้างปฏิทินกะ',
        p.machine_id, p.hour_start, CONCAT(N'sku=', p.sku, N' qty=', p.total_qty)
FROM    mfg.production_hour p
WHERE   NOT EXISTS (SELECT 1 FROM mfg.shift_calendar c
                    WHERE p.hour_start >= c.shift_start AND p.hour_start < c.shift_end)
UNION ALL
-- 5) Performance เกิน 105% แปลว่ารอบเวลามาตรฐานตั้งช้าเกินไป หรือบันทึกเวลาหยุดเกินจริง
SELECT  N'2-MEDIUM', N'PERFORMANCE_OVER_100', N'Performance เกิน 105% (ตรวจรอบเวลามาตรฐาน)',
        o.machine_id, o.shift_start,
        CONCAT(N'กะ ', o.shift_code, N' วันที่ ', CONVERT(NVARCHAR(10), o.prod_date, 120),
               N' ideal_run_min=', o.ideal_run_min, N' run_min=', o.run_min)
FROM    rpt.v_oee_shift o
WHERE   o.run_min >= 30 AND o.ideal_run_min > o.run_min * 1.05
UNION ALL
-- 6) ผลิตโดยไม่มีแผน
SELECT  N'2-MEDIUM', N'PRODUCTION_WITHOUT_PLAN', N'มียอดผลิตแต่ไม่มีแผน',
        o.machine_id, o.shift_start,
        CONCAT(N'กะ ', o.shift_code, N' วันที่ ', CONVERT(NVARCHAR(10), o.prod_date, 120), N' ผลิต ', o.total_qty, N' ชิ้น')
FROM    rpt.v_oee_shift o
WHERE   o.plan_qty = 0 AND o.total_qty > 0
UNION ALL
-- 7) การหยุดที่จบไปเกิน 24 ชม. แล้วแต่ยังไม่ระบุสาเหตุ
SELECT  N'2-MEDIUM', N'UNCODED_STOP', N'เครื่องหยุดแต่ยังไม่ระบุสาเหตุ (เกิน 24 ชม.)',
        e.machine_id, e.start_ts,
        CONCAT(N'event_id=', e.event_id, N' นาน ', DATEDIFF(MINUTE, e.start_ts, e.end_ts), N' นาที')
FROM    mfg.downtime_event e CROSS JOIN mfg.v_now n
WHERE   e.reason_code IS NULL AND e.end_ts IS NOT NULL AND e.end_ts < DATEADD(HOUR, -24, n.now_local)
UNION ALL
-- 8) รหัสสินค้าที่ไม่มีในตารางสินค้า
SELECT  N'3-LOW', N'UNKNOWN_SKU', N'รหัสสินค้าไม่มีในตาราง mfg.product',
        p.machine_id, MAX(p.hour_start), CONCAT(N'sku=', p.sku)
FROM    mfg.production_hour p
WHERE   NOT EXISTS (SELECT 1 FROM mfg.product pr WHERE pr.sku = p.sku)
GROUP BY p.machine_id, p.sku
UNION ALL
-- 9) ปฏิทินกะใกล้หมด (เหลือน้อยกว่า 30 วัน)
SELECT  N'1-HIGH', N'CALENDAR_ENDING', N'ปฏิทินกะจะหมดใน 30 วัน ให้รัน mfg.usp_build_shift_calendar',
        NULL, MAX(c.shift_end), CONCAT(N'ปฏิทินถึง ', CONVERT(NVARCHAR(16), MAX(c.shift_end), 120))
FROM    mfg.shift_calendar c CROSS JOIN mfg.v_now n
GROUP BY n.now_local
HAVING  MAX(c.shift_end) < DATEADD(DAY, 30, n.now_local)
UNION ALL
-- 10) ยอดผลิตลงเวลาในอนาคต (นาฬิกาเครื่อง/PLC ไม่ตรง)
SELECT  N'1-HIGH', N'FUTURE_TIMESTAMP', N'มีข้อมูลเวลาในอนาคต (ตรวจนาฬิกาเครื่อง/PLC)',
        p.machine_id, p.hour_start, CONCAT(N'sku=', p.sku)
FROM    mfg.production_hour p CROSS JOIN mfg.v_now n
WHERE   p.hour_start > n.now_local;
GO

/* =====================================================================
   ส่วนที่ 3: procedure ช่วยงาน
   ===================================================================== */

/* สร้างปฏิทินกะตามช่วงวันที่ (เพิ่มเฉพาะวันที่ยังไม่มี ไม่ทับของเดิม)
   ตัวอย่าง:
     EXEC mfg.usp_build_shift_calendar @date_from = '2026-01-01', @date_to = '2027-12-31';
     EXEC mfg.usp_build_shift_calendar '2026-01-01', '2027-12-31', @work_saturday = 0;  -- เสาร์หยุด */
CREATE OR ALTER PROCEDURE mfg.usp_build_shift_calendar
    @date_from     DATE,
    @date_to       DATE,
    @work_saturday BIT = 1,
    @work_sunday   BIT = 0
AS
BEGIN
    SET NOCOUNT ON;

    IF @date_to < @date_from OR DATEDIFF(DAY, @date_from, @date_to) > 3660
    BEGIN
        RAISERROR(N'ช่วงวันที่ไม่ถูกต้อง (date_to ต้องไม่น้อยกว่า date_from และไม่เกิน 10 ปี)', 16, 1);
        RETURN;
    END;

    IF NOT EXISTS (SELECT 1 FROM mfg.shift_definition WHERE is_active = 1)
    BEGIN
        RAISERROR(N'ยังไม่มีนิยามกะใน mfg.shift_definition', 16, 1);
        RETURN;
    END;

    WITH n AS (
        SELECT TOP (DATEDIFF(DAY, @date_from, @date_to) + 1)
               ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS i
        FROM   sys.all_columns a CROSS JOIN sys.all_columns b
    ),
    d AS (
        SELECT DATEADD(DAY, i, @date_from) AS prod_date,
               DATEDIFF(DAY, '19000101', DATEADD(DAY, i, @date_from)) % 7 AS dow   -- 0 = จันทร์ ... 5 = เสาร์, 6 = อาทิตย์
        FROM   n
    )
    INSERT INTO mfg.shift_calendar (prod_date, shift_code, shift_start, shift_end, is_working)
    SELECT  d.prod_date,
            s.shift_code,
            st.shift_start,
            DATEADD(MINUTE, s.duration_min, st.shift_start),
            CASE WHEN h.holiday_date IS NOT NULL         THEN 0
                 WHEN d.dow = 5 AND @work_saturday = 0   THEN 0
                 WHEN d.dow = 6 AND @work_sunday   = 0   THEN 0
                 ELSE 1 END
    FROM    d
    CROSS JOIN mfg.shift_definition s
    CROSS APPLY (SELECT DATEADD(HOUR, DATEPART(HOUR, s.start_time),
                         DATEADD(DAY, s.start_day_offset, CAST(d.prod_date AS DATETIME2(0)))) AS shift_start) st
    LEFT JOIN mfg.holiday h ON h.holiday_date = d.prod_date
    WHERE   s.is_active = 1
      AND   NOT EXISTS (SELECT 1 FROM mfg.shift_calendar c
                        WHERE c.prod_date = d.prod_date AND c.shift_code = s.shift_code)
      AND   NOT EXISTS (SELECT 1 FROM mfg.shift_calendar c
                        WHERE c.shift_start = st.shift_start);

    PRINT CONCAT(N'เพิ่มปฏิทินกะ ', @@ROWCOUNT, N' แถว');
END;
GO

/* บันทึกยอดผลิตรายชั่วโมง (ใช้กับ PLC / gateway / แบบฟอร์ม)
   - @ts         เวลาใดก็ได้ในชั่วโมงนั้น ระบบปัดลงเป็นต้นชั่วโมงให้
   - @sku        ถ้าไม่ส่งมา ระบบจะใช้สินค้าตามแผนของเครื่องในกะนั้น
   - @mode       'REPLACE' = ส่งยอดรวมทั้งชั่วโมง (เขียนทับ)
                 'ADD'     = ส่งยอดเพิ่ม เช่น ทุก 1 นาที (บวกเพิ่ม)
   ตัวอย่าง:
     EXEC mfg.usp_upsert_production_hour @machine_id = N'INJ-01', @ts = '2026-10-20 09:00',
          @total_qty = 120, @good_qty = 117, @sku = N'SKU-A01'; */
CREATE OR ALTER PROCEDURE mfg.usp_upsert_production_hour
    @machine_id NVARCHAR(20),
    @ts         DATETIME2(0),
    @total_qty  INT,
    @good_qty   INT,
    @sku        NVARCHAR(40) = NULL,
    @source     NVARCHAR(20) = N'PLC',
    @mode       VARCHAR(10)  = 'REPLACE'
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF @mode NOT IN ('REPLACE', 'ADD')
    BEGIN
        RAISERROR(N'@mode ต้องเป็น REPLACE หรือ ADD', 16, 1);
        RETURN;
    END;

    IF @total_qty < 0 OR @good_qty < 0 OR @good_qty > @total_qty
    BEGIN
        RAISERROR(N'จำนวนไม่ถูกต้อง (ต้องไม่ติดลบ และของดีต้องไม่เกินยอดรวม)', 16, 1);
        RETURN;
    END;

    DECLARE @hour_start DATETIME2(0) = DATEADD(HOUR, DATEDIFF(HOUR, CAST('2000-01-01' AS DATETIME2(0)), @ts), CAST('2000-01-01' AS DATETIME2(0)));

    IF @sku IS NULL
        SELECT TOP (1) @sku = pp.sku
        FROM   mfg.production_plan pp
        JOIN   mfg.shift_calendar c ON c.prod_date = pp.prod_date AND c.shift_code = pp.shift_code
        WHERE  pp.machine_id = @machine_id
          AND  @hour_start >= c.shift_start AND @hour_start < c.shift_end
        ORDER BY pp.plan_qty DESC, pp.sku;

    SET @sku = ISNULL(@sku, N'UNKNOWN');

    BEGIN TRANSACTION;

    UPDATE mfg.production_hour WITH (UPDLOCK, HOLDLOCK)
    SET    total_qty  = CASE WHEN @mode = 'ADD' THEN total_qty + @total_qty ELSE @total_qty END,
           good_qty   = CASE WHEN @mode = 'ADD' THEN good_qty  + @good_qty  ELSE @good_qty  END,
           source     = @source,
           updated_at = SYSDATETIME()
    WHERE  machine_id = @machine_id AND hour_start = @hour_start AND sku = @sku;

    IF @@ROWCOUNT = 0
        INSERT INTO mfg.production_hour (machine_id, hour_start, sku, total_qty, good_qty, source)
        VALUES (@machine_id, @hour_start, @sku, @total_qty, @good_qty, @source);

    COMMIT TRANSACTION;
END;
GO

/* เริ่มบันทึกเครื่องหยุด — ถ้าเครื่องนั้นมีการหยุดที่ยังเปิดอยู่แล้ว จะไม่สร้างซ้ำ
   ตัวอย่าง:  EXEC mfg.usp_downtime_start @machine_id = N'INJ-01';                    -- หยุดตอนนี้ ยังไม่รู้สาเหตุ
              EXEC mfg.usp_downtime_start N'INJ-01', '2026-10-20 10:15', N'BD-MECH';  -- ระบุเวลาและสาเหตุ */
CREATE OR ALTER PROCEDURE mfg.usp_downtime_start
    @machine_id  NVARCHAR(20),
    @start_ts    DATETIME2(0)  = NULL,
    @reason_code NVARCHAR(20)  = NULL,
    @note        NVARCHAR(400) = NULL,
    @source      NVARCHAR(20)  = N'MANUAL',
    @event_id    BIGINT        = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF @start_ts IS NULL SELECT @start_ts = now_local FROM mfg.v_now;

    BEGIN TRANSACTION;

    SELECT @event_id = event_id
    FROM   mfg.downtime_event WITH (UPDLOCK, HOLDLOCK)
    WHERE  machine_id = @machine_id AND end_ts IS NULL;

    IF @event_id IS NULL
    BEGIN
        INSERT INTO mfg.downtime_event (machine_id, start_ts, reason_code, note, source)
        VALUES (@machine_id, @start_ts, @reason_code, @note, @source);
        SET @event_id = SCOPE_IDENTITY();
    END;

    COMMIT TRANSACTION;
END;
GO

/* ปิดการหยุดที่ยังเปิดอยู่ของเครื่อง
   ตัวอย่าง:  EXEC mfg.usp_downtime_stop @machine_id = N'INJ-01';   -- จบตอนนี้ */
CREATE OR ALTER PROCEDURE mfg.usp_downtime_stop
    @machine_id NVARCHAR(20),
    @end_ts     DATETIME2(0) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @end_ts IS NULL SELECT @end_ts = now_local FROM mfg.v_now;

    UPDATE mfg.downtime_event
    SET    end_ts     = CASE WHEN @end_ts > start_ts THEN @end_ts ELSE DATEADD(SECOND, 1, start_ts) END,
           updated_at = SYSDATETIME()
    WHERE  machine_id = @machine_id AND end_ts IS NULL;
END;
GO

/* ระบุ/แก้สาเหตุการหยุด
   ตัวอย่าง:  EXEC mfg.usp_downtime_set_reason @event_id = 125, @reason_code = N'MAT-WAIT', @note = N'รอเม็ดพลาสติก'; */
CREATE OR ALTER PROCEDURE mfg.usp_downtime_set_reason
    @event_id    BIGINT,
    @reason_code NVARCHAR(20),
    @note        NVARCHAR(400) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE mfg.downtime_event
    SET    reason_code = @reason_code,
           note        = ISNULL(@note, note),
           updated_at  = SYSDATETIME()
    WHERE  event_id = @event_id;

    IF @@ROWCOUNT = 0
        RAISERROR(N'ไม่พบ event_id นี้', 16, 1);
END;
GO

PRINT N'02_views_and_procs.sql เสร็จ';
GO
SET NOEXEC OFF;
GO
