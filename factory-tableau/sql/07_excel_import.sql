/* =====================================================================
   07_excel_import.sql  —  นำเข้าข้อมูลจาก Excel (สำหรับโรงงานที่ยังไม่มีระบบดึงข้อมูลอัตโนมัติ)

   ไฟล์นี้สร้าง procedure 4 ตัว รันครั้งเดียวหลัง 02 (รันซ้ำได้):
     mfg.usp_import_master      เครื่องจักร / สินค้า + รอบเวลามาตรฐาน   (ตาราง dbo.stg_machine, dbo.stg_ct)
     mfg.usp_import_plan        แผนการผลิต                             (ตาราง dbo.stg_plan)
     mfg.usp_import_production  ยอดผลิตรายชั่วโมง                       (ตาราง dbo.stg_prod)
     mfg.usp_import_stops       เครื่องหยุด                              (ตาราง dbo.stg_stop)

   วิธีใช้ทุกครั้ง (ตัวอย่าง แผนการผลิต):
     1) Excel: แถวแรกเป็นชื่อคอลัมน์ตามที่กำหนด (ภาษาอังกฤษ ตัวพิมพ์เล็ก) → File → Save As → CSV UTF-8
     2) SSMS: คลิกขวาที่ฐานข้อมูล FactoryBI → Tasks → Import Flat File → เลือกไฟล์
        → ช่อง New table name ใส่ stg_plan (schema dbo) → Next ไปจนจบ
     3) New Query แล้วรัน:  EXEC mfg.usp_import_plan;
        - ถ้ามีแถวผิด จะแสดงตารางที่มีคอลัมน์ problem และยังไม่บันทึกอะไรเลย
          → แก้ใน Excel แล้วรัน DROP TABLE dbo.stg_plan; แล้วเริ่มข้อ 1 ใหม่
        - ถ้าผ่าน จะบันทึกและลบตาราง stg_plan ให้เอง

   รูปแบบวันที่ที่รับได้: 2026-10-21 หรือ 21/10/2026 (ปี พ.ศ. เช่น 21/10/2569 ระบบแปลงเป็น ค.ศ. ให้)
   วันเวลา: 2026-10-21 09:15 หรือ 21/10/2026 09:15 ; ตัวเลขมีจุลภาคได้ เช่น 1,200
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

-- อ่านวันที่/วันเวลาจากข้อความ: รับ yyyy-mm-dd [hh:mi] และ dd/mm/yyyy [hh:mi] ปี พ.ศ. แปลงเป็น ค.ศ.
CREATE OR ALTER FUNCTION mfg.tvf_parse_dt (@s NVARCHAR(40))
RETURNS TABLE
AS
RETURN
SELECT CASE WHEN x.d IS NULL         THEN NULL
            WHEN YEAR(x.d) > 2400    THEN DATEADD(YEAR, -543, x.d)
            ELSE x.d END AS dt
FROM (SELECT COALESCE(TRY_CONVERT(DATETIME2(0), LTRIM(RTRIM(@s)), 120),
                      TRY_CONVERT(DATETIME2(0), LTRIM(RTRIM(@s)), 103)) AS d) x;
GO

-- อ่านตัวเลขจากข้อความ (ตัดจุลภาค) ได้ค่าว่างถ้าไม่ใช่ตัวเลข
CREATE OR ALTER FUNCTION mfg.tvf_parse_num (@s NVARCHAR(40))
RETURNS TABLE
AS
RETURN
SELECT COALESCE(TRY_CAST(REPLACE(LTRIM(RTRIM(@s)), N',', N'') AS DECIMAL(18,3)),
                TRY_CAST(TRY_CAST(REPLACE(LTRIM(RTRIM(@s)), N',', N'') AS FLOAT) AS DECIMAL(18,3))) AS num;
GO

/* ---------------------------------------------------------------------
   เครื่องจักร / สินค้า + รอบเวลามาตรฐาน — ทำครั้งแรก และทุกครั้งที่มีเครื่องหรือสินค้าใหม่ก่อนเริ่มผลิต
   นำเข้าตารางใดตารางหนึ่งหรือทั้งสองก็ได้
     dbo.stg_machine : machine_id | machine_name | line_id | machine_type | is_active (1 = ใช้งาน, 0 = ไม่ใช้)
     dbo.stg_ct      : machine_id | sku | product_name | cycle_sec | pcs_per_cycle
        cycle_sec     = วินาทีต่อรอบ (ต่อช็อต / ต่อจังหวะปั๊ม) ที่เร็วที่สุดที่ทำได้จริงอย่างสม่ำเสมอ
        pcs_per_cycle = ได้กี่ชิ้นต่อรอบ (จำนวนคาวิตี้) ว่างไว้ = 1  → ระบบเก็บเป็น วินาที/ชิ้น = cycle_sec ÷ pcs_per_cycle
   --------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE mfg.usp_import_master
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF OBJECT_ID(N'dbo.stg_machine') IS NULL AND OBJECT_ID(N'dbo.stg_ct') IS NULL
    BEGIN
        RAISERROR(N'ยังไม่มีตาราง dbo.stg_machine หรือ dbo.stg_ct — นำเข้าไฟล์ด้วย Import Flat File ก่อน', 16, 1);
        RETURN;
    END;

    IF OBJECT_ID(N'dbo.stg_machine') IS NOT NULL
       AND (COL_LENGTH(N'dbo.stg_machine', N'machine_id') IS NULL OR COL_LENGTH(N'dbo.stg_machine', N'machine_name') IS NULL
            OR COL_LENGTH(N'dbo.stg_machine', N'line_id') IS NULL OR COL_LENGTH(N'dbo.stg_machine', N'machine_type') IS NULL
            OR COL_LENGTH(N'dbo.stg_machine', N'is_active') IS NULL)
    BEGIN
        RAISERROR(N'ตาราง dbo.stg_machine ต้องมีคอลัมน์: machine_id, machine_name, line_id, machine_type, is_active', 16, 1);
        RETURN;
    END;

    IF OBJECT_ID(N'dbo.stg_ct') IS NOT NULL
       AND (COL_LENGTH(N'dbo.stg_ct', N'machine_id') IS NULL OR COL_LENGTH(N'dbo.stg_ct', N'sku') IS NULL
            OR COL_LENGTH(N'dbo.stg_ct', N'product_name') IS NULL OR COL_LENGTH(N'dbo.stg_ct', N'cycle_sec') IS NULL
            OR COL_LENGTH(N'dbo.stg_ct', N'pcs_per_cycle') IS NULL)
    BEGIN
        RAISERROR(N'ตาราง dbo.stg_ct ต้องมีคอลัมน์: machine_id, sku, product_name, cycle_sec, pcs_per_cycle', 16, 1);
        RETURN;
    END;

    CREATE TABLE #m (machine_id NVARCHAR(100), machine_name NVARCHAR(200), line_id NVARCHAR(100), machine_type NVARCHAR(100), is_active_text NVARCHAR(40));
    CREATE TABLE #c (machine_id NVARCHAR(100), sku NVARCHAR(100), product_name NVARCHAR(200), cycle_text NVARCHAR(40), pcs_text NVARCHAR(40));

    IF OBJECT_ID(N'dbo.stg_machine') IS NOT NULL
        EXEC (N'INSERT INTO #m SELECT LTRIM(RTRIM(CONVERT(NVARCHAR(100), machine_id))), CONVERT(NVARCHAR(200), machine_name),
                     LTRIM(RTRIM(CONVERT(NVARCHAR(100), line_id))), CONVERT(NVARCHAR(100), machine_type), CONVERT(NVARCHAR(40), is_active)
               FROM dbo.stg_machine');
    IF OBJECT_ID(N'dbo.stg_ct') IS NOT NULL
        EXEC (N'INSERT INTO #c SELECT LTRIM(RTRIM(CONVERT(NVARCHAR(100), machine_id))), LTRIM(RTRIM(CONVERT(NVARCHAR(100), sku))),
                     CONVERT(NVARCHAR(200), product_name), CONVERT(NVARCHAR(40), cycle_sec), CONVERT(NVARCHAR(40), pcs_per_cycle)
               FROM dbo.stg_ct');

    -- ตรวจแถวผิด
    SELECT  CAST(N'stg_machine' AS NVARCHAR(20)) AS [ตาราง], m.machine_id, m.machine_name, m.line_id, CAST(NULL AS NVARCHAR(100)) AS sku,
            CAST(CASE WHEN ISNULL(m.machine_id, N'') = N''                THEN N'machine_id ว่าง'
                 WHEN LEN(m.machine_id) > 20                         THEN N'machine_id ยาวเกิน 20 ตัวอักษร'
                 WHEN ISNULL(m.line_id, N'') = N''                   THEN N'line_id ว่าง'
                 WHEN ISNULL(m.is_active_text, N'') NOT IN (N'', N'0', N'1') THEN N'is_active ต้องเป็น 1 หรือ 0'
            END AS NVARCHAR(200)) AS problem
    INTO    #bad
    FROM    #m m;

    INSERT INTO #bad
    SELECT  N'stg_ct', c.machine_id, NULL, NULL, c.sku,
            CASE WHEN ISNULL(c.sku, N'') = N''                        THEN N'sku ว่าง'
                 WHEN LEN(c.sku) > 40                                 THEN N'sku ยาวเกิน 40 ตัวอักษร'
                 WHEN NOT EXISTS (SELECT 1 FROM mfg.machine x WHERE x.machine_id = c.machine_id)
                  AND NOT EXISTS (SELECT 1 FROM #m x WHERE x.machine_id = c.machine_id)
                                                                      THEN N'ไม่มีรหัสเครื่องนี้ (เพิ่มใน stg_machine ก่อน)'
                 WHEN ISNULL(cy.num, 0) <= 0                          THEN N'cycle_sec ต้องเป็นตัวเลขมากกว่า 0'
                 WHEN NULLIF(c.pcs_text, N'') IS NOT NULL AND (pc.num IS NULL OR pc.num <= 0)
                                                                      THEN N'pcs_per_cycle ต้องเป็นตัวเลขมากกว่า 0 (ว่างไว้ = 1)'
            END
    FROM    #c c
    CROSS APPLY mfg.tvf_parse_num(c.cycle_text) cy
    CROSS APPLY mfg.tvf_parse_num(NULLIF(c.pcs_text, N'')) pc;

    IF EXISTS (SELECT 1 FROM #bad WHERE problem IS NOT NULL)
    BEGIN
        SELECT * FROM #bad WHERE problem IS NOT NULL;
        RAISERROR(N'มีแถวที่ไม่ถูกต้อง (ดูตารางผลลัพธ์) ยังไม่ได้บันทึกอะไร — แก้ใน Excel แล้ว DROP TABLE ตาราง stg ที่ผิด แล้วนำเข้าใหม่', 16, 1);
        RETURN;
    END;

    BEGIN TRANSACTION;

    MERGE mfg.machine AS t
    USING (SELECT machine_id, machine_name, line_id, machine_type,
                  CASE WHEN is_active_text = N'0' THEN 0 ELSE 1 END AS is_active
           FROM  (SELECT *, ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY machine_name DESC) AS rn FROM #m) x
           WHERE rn = 1) AS s
    ON  t.machine_id = s.machine_id
    WHEN MATCHED THEN
        UPDATE SET machine_name = ISNULL(s.machine_name, t.machine_name), line_id = s.line_id,
                   machine_type = s.machine_type, is_active = s.is_active
    WHEN NOT MATCHED THEN
        INSERT (machine_id, machine_name, line_id, machine_type, is_active)
        VALUES (s.machine_id, ISNULL(s.machine_name, s.machine_id), s.line_id, s.machine_type, s.is_active);

    INSERT INTO mfg.product (sku, product_name)
    SELECT c.sku, MAX(ISNULL(NULLIF(c.product_name, N''), c.sku))   -- ISNULL ทำให้ไม่มีค่าว่างใน MAX
    FROM   #c c
    WHERE  NOT EXISTS (SELECT 1 FROM mfg.product p WHERE p.sku = c.sku)
    GROUP BY c.sku;

    MERGE mfg.std_cycle_time AS t
    USING (SELECT c.machine_id, c.sku, CAST(MIN(cy.num / ISNULL(pc.num, 1)) AS DECIMAL(10,3)) AS ideal_ct_sec
           FROM   #c c
           CROSS APPLY mfg.tvf_parse_num(c.cycle_text) cy
           CROSS APPLY mfg.tvf_parse_num(NULLIF(c.pcs_text, N'')) pc
           GROUP BY c.machine_id, c.sku) AS s
    ON  t.machine_id = s.machine_id AND t.sku = s.sku
    WHEN MATCHED THEN UPDATE SET ideal_ct_sec = s.ideal_ct_sec
    WHEN NOT MATCHED THEN INSERT (machine_id, sku, ideal_ct_sec) VALUES (s.machine_id, s.sku, s.ideal_ct_sec);

    COMMIT TRANSACTION;

    IF OBJECT_ID(N'dbo.stg_machine') IS NOT NULL DROP TABLE dbo.stg_machine;
    IF OBJECT_ID(N'dbo.stg_ct') IS NOT NULL DROP TABLE dbo.stg_ct;
    DECLARE @nm INT = (SELECT COUNT(*) FROM #m), @nc INT = (SELECT COUNT(*) FROM #c);
    PRINT CONCAT(N'นำเข้าเรียบร้อย: เครื่องจักร ', @nm, N' แถว, รอบเวลามาตรฐาน ', @nc, N' แถว');
END;
GO

/* ---------------------------------------------------------------------
   แผนการผลิต — ทำทุกครั้งที่ฝ่ายวางแผนออกแผนใหม่หรือแก้แผน
     dbo.stg_plan : prod_date | shift_code | machine_id | sku | plan_qty
       prod_date  = วันผลิตตามปฏิทินกะ (กะดึกที่ข้ามเที่ยงคืนใช้วันที่เริ่มกะ ยกเว้นตั้ง start_day_offset ไว้ต่างจากนี้)
       shift_code = รหัสกะในระบบ (เช่น D / N) ไม่ใช่คำว่า เช้า / ดึก
   สำคัญ: ไฟล์ต้องมีแผนของ "ทุกเครื่อง" ใน วันที่+กะ ที่อยู่ในไฟล์
          แผนเดิมของ วันที่+กะ นั้นที่ไม่อยู่ในไฟล์ใหม่จะถูกลบ (เช่น ย้ายงานไปเครื่องอื่น)
   ผลลัพธ์แสดงทุกแถวที่เปลี่ยน: INSERT = เพิ่ม, UPDATE = แก้จำนวน, DELETE = แผนเดิมที่ถูกลบ
   --------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE mfg.usp_import_plan
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF OBJECT_ID(N'dbo.stg_plan') IS NULL
    BEGIN
        RAISERROR(N'ยังไม่มีตาราง dbo.stg_plan — นำเข้าไฟล์แผนด้วย Import Flat File ก่อน (ตั้งชื่อตาราง stg_plan)', 16, 1);
        RETURN;
    END;
    IF COL_LENGTH(N'dbo.stg_plan', N'prod_date') IS NULL OR COL_LENGTH(N'dbo.stg_plan', N'shift_code') IS NULL
       OR COL_LENGTH(N'dbo.stg_plan', N'machine_id') IS NULL OR COL_LENGTH(N'dbo.stg_plan', N'sku') IS NULL
       OR COL_LENGTH(N'dbo.stg_plan', N'plan_qty') IS NULL
    BEGIN
        RAISERROR(N'ตาราง dbo.stg_plan ต้องมีคอลัมน์: prod_date, shift_code, machine_id, sku, plan_qty', 16, 1);
        RETURN;
    END;

    CREATE TABLE #raw (prod_date_text NVARCHAR(40), shift_code NVARCHAR(100), machine_id NVARCHAR(100), sku NVARCHAR(100), qty_text NVARCHAR(40));
    EXEC (N'INSERT INTO #raw SELECT CONVERT(NVARCHAR(40), prod_date, 120), LTRIM(RTRIM(CONVERT(NVARCHAR(100), shift_code))),
                 LTRIM(RTRIM(CONVERT(NVARCHAR(100), machine_id))), LTRIM(RTRIM(CONVERT(NVARCHAR(100), sku))), CONVERT(NVARCHAR(40), plan_qty)
           FROM dbo.stg_plan');

    SELECT  r.*, CAST(d.dt AS DATE) AS prod_date, q.num AS plan_qty,
            CASE WHEN d.dt IS NULL                                       THEN N'วันที่อ่านไม่ได้ (ใช้ 2026-10-21 หรือ 21/10/2026)'
                 WHEN q.num IS NULL OR q.num < 0 OR q.num <> FLOOR(q.num) THEN N'plan_qty ต้องเป็นจำนวนเต็มไม่ติดลบ'
                 WHEN NOT EXISTS (SELECT 1 FROM mfg.shift_calendar c WHERE c.prod_date = CAST(d.dt AS DATE) AND c.shift_code = r.shift_code)
                                                                          THEN N'ไม่มีวันที่/กะนี้ในปฏิทินกะ (shift_code ต้องเป็นรหัสกะ เช่น D/N)'
                 WHEN NOT EXISTS (SELECT 1 FROM mfg.machine m WHERE m.machine_id = r.machine_id)
                                                                          THEN N'ไม่มีรหัสเครื่องนี้ใน mfg.machine'
                 WHEN NOT EXISTS (SELECT 1 FROM mfg.std_cycle_time ct WHERE ct.machine_id = r.machine_id AND ct.sku = r.sku)
                                                                          THEN N'ไม่มีรอบเวลามาตรฐานของสินค้านี้บนเครื่องนี้ (นำเข้าด้วย usp_import_master ก่อน)'
            END AS problem
    INTO    #s
    FROM    #raw r
    CROSS APPLY mfg.tvf_parse_dt(r.prod_date_text) d
    CROSS APPLY mfg.tvf_parse_num(r.qty_text) q;

    IF EXISTS (SELECT 1 FROM #s WHERE problem IS NOT NULL)
    BEGIN
        SELECT prod_date_text, shift_code, machine_id, sku, qty_text AS plan_qty, problem FROM #s WHERE problem IS NOT NULL;
        RAISERROR(N'มีแถวที่ไม่ถูกต้อง (ดูตารางผลลัพธ์) ยังไม่ได้บันทึกอะไร — แก้ใน Excel แล้ว DROP TABLE dbo.stg_plan; แล้วนำเข้าใหม่', 16, 1);
        RETURN;
    END;

    BEGIN TRANSACTION;

    WITH src AS (
        SELECT prod_date, shift_code, machine_id, sku, CAST(SUM(plan_qty) AS INT) AS plan_qty
        FROM   #s
        GROUP BY prod_date, shift_code, machine_id, sku
    ),
    tgt AS (
        SELECT p.*
        FROM   mfg.production_plan p
        WHERE  EXISTS (SELECT 1 FROM #s x WHERE x.prod_date = p.prod_date AND x.shift_code = p.shift_code)
    )
    MERGE tgt AS t
    USING src AS s
    ON  t.prod_date = s.prod_date AND t.shift_code = s.shift_code AND t.machine_id = s.machine_id AND t.sku = s.sku
    WHEN MATCHED AND t.plan_qty <> s.plan_qty THEN
        UPDATE SET plan_qty = s.plan_qty, source = N'EXCEL', updated_at = (SELECT now_local FROM mfg.v_now)
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (prod_date, shift_code, machine_id, sku, plan_qty, source)
        VALUES (s.prod_date, s.shift_code, s.machine_id, s.sku, s.plan_qty, N'EXCEL')
    WHEN NOT MATCHED BY SOURCE THEN
        DELETE
    OUTPUT  $action                                       AS [การเปลี่ยนแปลง],
            ISNULL(inserted.prod_date,  deleted.prod_date)  AS prod_date,
            ISNULL(inserted.shift_code, deleted.shift_code) AS shift_code,
            ISNULL(inserted.machine_id, deleted.machine_id) AS machine_id,
            ISNULL(inserted.sku,        deleted.sku)        AS sku,
            deleted.plan_qty                              AS [แผนเดิม],
            inserted.plan_qty                             AS [แผนใหม่];

    COMMIT TRANSACTION;

    DROP TABLE dbo.stg_plan;
    DECLARE @n INT = (SELECT COUNT(*) FROM #s);
    PRINT CONCAT(N'นำเข้าแผนเรียบร้อย (', @n, N' แถวในไฟล์) — ตรวจตารางผลลัพธ์: แถว DELETE คือแผนเดิมที่ถูกลบ');
END;
GO

/* ---------------------------------------------------------------------
   ยอดผลิตรายชั่วโมง — กรอกทุก 1-2 ชม. (หรืออย่างน้อยทุกกะ) นำเข้าซ้ำได้ ชั่วโมงเดิมจะถูกเขียนทับ
     dbo.stg_prod : machine_id | hour_start | sku | total_qty | good_qty
       hour_start = เวลาใดก็ได้ในชั่วโมงนั้น เช่น 2026-10-21 09:00 (ระบบปัดลงเป็นต้นชั่วโมง)
       sku ว่างได้ (ระบบใช้สินค้าตามแผน) ; total_qty = ผลิตทั้งหมด (ดี+เสีย) ; good_qty = ของดี
   --------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE mfg.usp_import_production
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF OBJECT_ID(N'dbo.stg_prod') IS NULL
    BEGIN
        RAISERROR(N'ยังไม่มีตาราง dbo.stg_prod — นำเข้าไฟล์ยอดผลิตด้วย Import Flat File ก่อน (ตั้งชื่อตาราง stg_prod)', 16, 1);
        RETURN;
    END;
    IF COL_LENGTH(N'dbo.stg_prod', N'machine_id') IS NULL OR COL_LENGTH(N'dbo.stg_prod', N'hour_start') IS NULL
       OR COL_LENGTH(N'dbo.stg_prod', N'sku') IS NULL OR COL_LENGTH(N'dbo.stg_prod', N'total_qty') IS NULL
       OR COL_LENGTH(N'dbo.stg_prod', N'good_qty') IS NULL
    BEGIN
        RAISERROR(N'ตาราง dbo.stg_prod ต้องมีคอลัมน์: machine_id, hour_start, sku, total_qty, good_qty', 16, 1);
        RETURN;
    END;

    DECLARE @now DATETIME2(0) = (SELECT now_local FROM mfg.v_now);

    CREATE TABLE #raw (machine_id NVARCHAR(100), ts_text NVARCHAR(40), sku NVARCHAR(100), total_text NVARCHAR(40), good_text NVARCHAR(40));
    EXEC (N'INSERT INTO #raw SELECT LTRIM(RTRIM(CONVERT(NVARCHAR(100), machine_id))), CONVERT(NVARCHAR(40), hour_start, 120),
                 NULLIF(LTRIM(RTRIM(CONVERT(NVARCHAR(100), sku))), N''''), CONVERT(NVARCHAR(40), total_qty), CONVERT(NVARCHAR(40), good_qty)
           FROM dbo.stg_prod');

    SELECT  r.*, hs.hour_start, t.num AS total_qty, g.num AS good_qty,
            CASE WHEN d.dt IS NULL                                        THEN N'เวลาอ่านไม่ได้ (ใช้ 2026-10-21 09:00 หรือ 21/10/2026 09:00)'
                 WHEN d.dt > @now                                         THEN N'เวลาอยู่ในอนาคต'
                 WHEN NOT EXISTS (SELECT 1 FROM mfg.machine m WHERE m.machine_id = r.machine_id)
                                                                          THEN N'ไม่มีรหัสเครื่องนี้ใน mfg.machine'
                 WHEN t.num IS NULL OR t.num < 0 OR t.num <> FLOOR(t.num) THEN N'total_qty ต้องเป็นจำนวนเต็มไม่ติดลบ'
                 WHEN g.num IS NULL OR g.num < 0 OR g.num <> FLOOR(g.num) THEN N'good_qty ต้องเป็นจำนวนเต็มไม่ติดลบ'
                 WHEN g.num > t.num                                       THEN N'ของดี (good_qty) มากกว่ายอดรวม (total_qty)'
            END AS problem
    INTO    #s
    FROM    #raw r
    CROSS APPLY mfg.tvf_parse_dt(r.ts_text) d
    CROSS APPLY (SELECT DATEADD(HOUR, DATEDIFF(HOUR, CAST('2000-01-01' AS DATETIME2(0)), d.dt), CAST('2000-01-01' AS DATETIME2(0))) AS hour_start) hs
    CROSS APPLY mfg.tvf_parse_num(r.total_text) t
    CROSS APPLY mfg.tvf_parse_num(r.good_text) g;

    IF EXISTS (SELECT 1 FROM #s WHERE problem IS NOT NULL)
    BEGIN
        SELECT machine_id, ts_text AS hour_start, sku, total_text AS total_qty, good_text AS good_qty, problem FROM #s WHERE problem IS NOT NULL;
        RAISERROR(N'มีแถวที่ไม่ถูกต้อง (ดูตารางผลลัพธ์) ยังไม่ได้บันทึกอะไร — แก้ใน Excel แล้ว DROP TABLE dbo.stg_prod; แล้วนำเข้าใหม่', 16, 1);
        RETURN;
    END;

    -- sku ว่าง: ใช้สินค้าตามแผนของเครื่องในกะนั้น
    UPDATE s
    SET    sku = ISNULL((SELECT TOP (1) pp.sku
                         FROM   mfg.production_plan pp
                         JOIN   mfg.shift_calendar c ON c.prod_date = pp.prod_date AND c.shift_code = pp.shift_code
                         WHERE  pp.machine_id = s.machine_id
                           AND  s.hour_start >= c.shift_start AND s.hour_start < c.shift_end
                         ORDER BY pp.plan_qty DESC, pp.sku), N'UNKNOWN')
    FROM   #s s
    WHERE  s.sku IS NULL;

    BEGIN TRANSACTION;

    MERGE mfg.production_hour AS t
    USING (SELECT machine_id, hour_start, sku, CAST(SUM(total_qty) AS INT) AS total_qty, CAST(SUM(good_qty) AS INT) AS good_qty
           FROM #s GROUP BY machine_id, hour_start, sku) AS s
    ON  t.machine_id = s.machine_id AND t.hour_start = s.hour_start AND t.sku = s.sku
    WHEN MATCHED THEN
        UPDATE SET total_qty  = s.total_qty,
                   good_qty   = CASE WHEN s.good_qty > t.qc_scrap_qty THEN s.good_qty - t.qc_scrap_qty ELSE 0 END,  -- คงของเสียที่ QC บันทึกไว้
                   source     = N'FORM',
                   updated_at = @now
    WHEN NOT MATCHED THEN
        INSERT (machine_id, hour_start, sku, total_qty, good_qty, source)
        VALUES (s.machine_id, s.hour_start, s.sku, s.total_qty, s.good_qty, N'FORM');

    COMMIT TRANSACTION;

    DROP TABLE dbo.stg_prod;
    DECLARE @n INT = (SELECT COUNT(*) FROM #s);
    PRINT CONCAT(N'นำเข้ายอดผลิตเรียบร้อย ', @n, N' แถว');
END;
GO

/* ---------------------------------------------------------------------
   เครื่องหยุด — นำเข้าซ้ำได้ (รายการที่ machine_id + start_ts ตรงกัน จะถูกอัปเดต ไม่สร้างซ้ำ)
     dbo.stg_stop : machine_id | start_ts | end_ts | reason_code | note
       end_ts ว่าง = ยังหยุดอยู่ ; reason_code ว่าง = ยังไม่รู้สาเหตุ (ต้องเป็นรหัสใน mfg.downtime_reason)
   --------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE mfg.usp_import_stops
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF OBJECT_ID(N'dbo.stg_stop') IS NULL
    BEGIN
        RAISERROR(N'ยังไม่มีตาราง dbo.stg_stop — นำเข้าไฟล์เครื่องหยุดด้วย Import Flat File ก่อน (ตั้งชื่อตาราง stg_stop)', 16, 1);
        RETURN;
    END;
    IF COL_LENGTH(N'dbo.stg_stop', N'machine_id') IS NULL OR COL_LENGTH(N'dbo.stg_stop', N'start_ts') IS NULL
       OR COL_LENGTH(N'dbo.stg_stop', N'end_ts') IS NULL OR COL_LENGTH(N'dbo.stg_stop', N'reason_code') IS NULL
       OR COL_LENGTH(N'dbo.stg_stop', N'note') IS NULL
    BEGIN
        RAISERROR(N'ตาราง dbo.stg_stop ต้องมีคอลัมน์: machine_id, start_ts, end_ts, reason_code, note', 16, 1);
        RETURN;
    END;

    DECLARE @now DATETIME2(0) = (SELECT now_local FROM mfg.v_now);

    CREATE TABLE #raw (machine_id NVARCHAR(100), start_text NVARCHAR(40), end_text NVARCHAR(40), reason_code NVARCHAR(100), note NVARCHAR(400));
    EXEC (N'INSERT INTO #raw SELECT LTRIM(RTRIM(CONVERT(NVARCHAR(100), machine_id))), CONVERT(NVARCHAR(40), start_ts, 120),
                 NULLIF(LTRIM(RTRIM(CONVERT(NVARCHAR(40), end_ts, 120))), N''''), NULLIF(LTRIM(RTRIM(CONVERT(NVARCHAR(100), reason_code))), N''''),
                 NULLIF(CONVERT(NVARCHAR(400), note), N'''')
           FROM dbo.stg_stop');

    SELECT  r.*, st.dt AS start_ts, en.dt AS end_ts,
            CASE WHEN st.dt IS NULL                                       THEN N'start_ts อ่านไม่ได้ (ใช้ 2026-10-21 09:15 หรือ 21/10/2026 09:15)'
                 WHEN r.end_text IS NOT NULL AND en.dt IS NULL            THEN N'end_ts อ่านไม่ได้'
                 WHEN en.dt <= st.dt                                      THEN N'end_ts ต้องหลัง start_ts'
                 WHEN st.dt > @now                                        THEN N'start_ts อยู่ในอนาคต'
                 WHEN NOT EXISTS (SELECT 1 FROM mfg.machine m WHERE m.machine_id = r.machine_id)
                                                                          THEN N'ไม่มีรหัสเครื่องนี้ใน mfg.machine'
                 WHEN r.reason_code IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM mfg.downtime_reason x WHERE x.reason_code = r.reason_code)
                                                                          THEN N'reason_code ไม่มีใน mfg.downtime_reason'
            END AS problem
    INTO    #s
    FROM    #raw r
    CROSS APPLY mfg.tvf_parse_dt(r.start_text) st
    CROSS APPLY mfg.tvf_parse_dt(r.end_text) en;

    IF EXISTS (SELECT 1 FROM #s WHERE problem IS NOT NULL)
    BEGIN
        SELECT machine_id, start_text AS start_ts, end_text AS end_ts, reason_code, problem FROM #s WHERE problem IS NOT NULL;
        RAISERROR(N'มีแถวที่ไม่ถูกต้อง (ดูตารางผลลัพธ์) ยังไม่ได้บันทึกอะไร — แก้ใน Excel แล้ว DROP TABLE dbo.stg_stop; แล้วนำเข้าใหม่', 16, 1);
        RETURN;
    END;

    BEGIN TRANSACTION;

    MERGE mfg.downtime_event AS t
    USING (SELECT machine_id, start_ts, end_ts, reason_code, note
           FROM  (SELECT *, ROW_NUMBER() OVER (PARTITION BY machine_id, start_ts ORDER BY end_ts DESC) AS rn FROM #s) x
           WHERE rn = 1) AS s
    ON  t.machine_id = s.machine_id AND t.start_ts = s.start_ts
    WHEN MATCHED THEN
        UPDATE SET end_ts      = s.end_ts,
                   reason_code = ISNULL(s.reason_code, t.reason_code),
                   note        = ISNULL(s.note, t.note),
                   updated_at  = @now
    WHEN NOT MATCHED THEN
        INSERT (machine_id, start_ts, end_ts, reason_code, note, source)
        VALUES (s.machine_id, s.start_ts, s.end_ts, s.reason_code, s.note, N'FORM');

    COMMIT TRANSACTION;

    DROP TABLE dbo.stg_stop;
    DECLARE @n INT = (SELECT COUNT(*) FROM #s);
    PRINT CONCAT(N'นำเข้าเครื่องหยุดเรียบร้อย ', @n, N' แถว');
END;
GO

PRINT N'07_excel_import.sql เสร็จ';
GO
SET NOEXEC OFF;
GO
