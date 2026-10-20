/* =====================================================================
   06_load_from_existing_TEMPLATE.sql  —  แม่แบบ: ดึงข้อมูลจากตารางเดิมของโรงงานเข้า mfg

   ใช้เมื่อโรงงานมีตารางเก็บยอดผลิต/เครื่องหยุดอยู่แล้ว (จาก PLC, MES, โปรแกรมเดิม)
   แทนที่จะให้ระบบเดิมเขียนเข้า mfg โดยตรง ให้ตั้งเวลา (ทุก 15-60 นาที) รัน procedure นี้
   (ถ้ายังไม่มีระบบเดิม ให้กรอก Excel แล้วนำเข้าด้วย 07_excel_import.sql แทน)

   ขั้นตอน:
     1) รันไฟล์นี้ทั้งไฟล์ได้เลยครั้งแรก (ส่วนเพิ่มคอลัมน์ source_ref จะทำงาน ส่วนแม่แบบยังเป็นคอมเมนต์)
     2) แก้ชื่อในเครื่องหมาย <<...>> ในแม่แบบให้ครบ ลบบรรทัด BEGIN-TEMPLATE / END-TEMPLATE แล้วรันอีกครั้ง
     3) ทดสอบ: EXEC mfg.usp_load_from_existing;  แล้วตั้งเวลาให้รันอัตโนมัติ

   >>> ไฟล์นี้เป็นแม่แบบ ต้องแก้ชื่อตาราง/คอลัมน์ในเครื่องหมาย <<...>> ให้ตรงกับของจริงก่อน <<<
   ถ้าไม่แน่ใจ ส่งผลของคำสั่งนี้มาให้ช่วยแก้ได้ (ส่งแค่โครงสร้าง ไม่ต้องส่งข้อมูล):
       SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
       FROM INFORMATION_SCHEMA.COLUMNS ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;

   การตั้งเวลา:
     - SQL Server รุ่น Standard/Enterprise: ใช้ SQL Server Agent สร้าง Job รัน
         EXEC mfg.usp_load_from_existing;
     - SQL Server Express (ไม่มี Agent): Windows Task Scheduler → Create Task → Triggers: ทุก 15 นาที
       → Actions: Program = sqlcmd , Arguments =
         -S .\SQLEXPRESS -d FactoryBI -E -C -b -Q "EXEC mfg.usp_load_from_existing" -o C:\FactoryBI\load_log.txt
       -S  ใส่ชื่อเดียวกับที่ใช้ต่อ SSMS
       -E  ใช้บัญชี Windows ที่ตั้งใน Task ซึ่งต้องมีสิทธิ์ในฐานข้อมูล FactoryBI
       -b  ถ้า error ให้ Task แสดงว่าล้มเหลว (ไม่ใส่จะขึ้นว่าสำเร็จเสมอ แม้ดึงข้อมูลไม่ได้)
       -C  ใช้เมื่อ sqlcmd รุ่นใหม่ขึ้น error เรื่องใบรับรอง (certificate)
       ตรวจทุกวันที่ Task Scheduler → History (Last Run Result ต้องเป็น 0x0) และไฟล์ load_log.txt
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

-- ทำครั้งแรกครั้งเดียว (รันได้เลย ไม่ต้องแก้): คอลัมน์เก็บรหัสการหยุดจากระบบเดิม เพื่อไม่ให้ข้อมูลซ้ำเวลาดึงซ้ำ
IF COL_LENGTH(N'mfg.downtime_event', N'source_ref') IS NULL
    ALTER TABLE mfg.downtime_event ADD source_ref NVARCHAR(100) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_downtime_source_ref' AND object_id = OBJECT_ID(N'mfg.downtime_event'))
    CREATE UNIQUE INDEX UX_downtime_source_ref ON mfg.downtime_event (source_ref) WHERE source_ref IS NOT NULL;
GO

/* BEGIN-TEMPLATE  <<< แก้ชื่อในเครื่องหมาย <<...>> ให้ครบ แล้วลบบรรทัดนี้ทั้งบรรทัด

CREATE OR ALTER PROCEDURE mfg.usp_load_from_existing
    @days_back INT = 3          -- ดึงย้อนหลังกี่วัน (ดึงซ้ำได้ ไม่เกิดข้อมูลซ้ำ)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @now   DATETIME2(0) = (SELECT now_local FROM mfg.v_now);
    DECLARE @since DATETIME2(0) = DATEADD(DAY, -@days_back, @now);
    -- ปัดลงเป็นต้นชั่วโมง เพื่อให้ชั่วโมงแรกของช่วงที่ดึง ได้ยอดครบทั้งชั่วโมง (ไม่งั้นจะเขียนทับด้วยยอดครึ่งชั่วโมง)
    SET @since = DATEADD(HOUR, DATEDIFF(HOUR, CAST('2000-01-01' AS DATETIME2(0)), @since), CAST('2000-01-01' AS DATETIME2(0)));

    BEGIN TRANSACTION;

    -- 1) ยอดผลิต: รวมเป็นรายชั่วโมงแล้วเขียนทับ (MERGE)
    --    ถ้าตารางเดิมเก็บเป็น "ทีละชิ้น" หรือ "ทีละนาที" ให้ SUM ตามด้านล่าง
    --    ถ้าตารางเดิมเก็บ "ตัวนับสะสม" ของ PLC ต้องคำนวณส่วนต่างก่อน (ส่งโครงสร้างมาให้ช่วยเขียนได้)
    MERGE mfg.production_hour AS t
    USING (
        SELECT  src.<<machine_col>>                                        AS machine_id,
                DATEADD(HOUR, DATEDIFF(HOUR, 0, src.<<timestamp_col>>), 0) AS hour_start,
                ISNULL(src.<<sku_col>>, N'UNKNOWN')                         AS sku,
                SUM(src.<<total_qty_col>>)                                  AS total_qty,
                SUM(src.<<good_qty_col>>)                                   AS good_qty      -- ถ้ามีแต่ของเสีย: SUM(total - ng)
        FROM    <<schema>>.<<production_table>> src
        WHERE   src.<<timestamp_col>> >= @since
          AND   EXISTS (SELECT 1 FROM mfg.machine m WHERE m.machine_id = src.<<machine_col>>)   -- ข้ามเครื่องที่ยังไม่มีใน mfg.machine
        GROUP BY src.<<machine_col>>, DATEADD(HOUR, DATEDIFF(HOUR, 0, src.<<timestamp_col>>), 0), ISNULL(src.<<sku_col>>, N'UNKNOWN')
        HAVING  SUM(src.<<good_qty_col>>) >= 0 AND SUM(src.<<total_qty_col>>) >= SUM(src.<<good_qty_col>>)   -- ข้ามยอดที่ผิด
    ) AS s
    ON  t.machine_id = s.machine_id AND t.hour_start = s.hour_start AND t.sku = s.sku
    -- good_qty หักของเสียที่ QC บันทึกภายหลัง (qc_scrap_qty) ไว้เสมอ ไม่ให้การดึงซ้ำล้างของเสียทิ้ง
    WHEN MATCHED AND (t.total_qty <> s.total_qty
                      OR t.good_qty <> CASE WHEN s.good_qty > t.qc_scrap_qty THEN s.good_qty - t.qc_scrap_qty ELSE 0 END) THEN
        UPDATE SET total_qty  = s.total_qty,
                   good_qty   = CASE WHEN s.good_qty > t.qc_scrap_qty THEN s.good_qty - t.qc_scrap_qty ELSE 0 END,
                   source     = N'IMPORT',
                   updated_at = @now
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (machine_id, hour_start, sku, total_qty, good_qty, source)
        VALUES (s.machine_id, s.hour_start, s.sku, s.total_qty, s.good_qty, N'IMPORT');

    -- 2) เครื่องหยุด: ใช้รหัสอ้างอิงจากระบบเดิม (source_ref) เพื่อไม่ให้ซ้ำเวลาดึงซ้ำ
    MERGE mfg.downtime_event AS t
    USING (
        SELECT  CAST(src.<<stop_id_col>> AS NVARCHAR(100)) AS source_ref,
                src.<<machine_col>>      AS machine_id,
                src.<<stop_start_col>>   AS start_ts,
                src.<<stop_end_col>>     AS end_ts,          -- ว่างได้ถ้ายังไม่จบ
                map.reason_code          AS reason_code       -- แปลงรหัสเดิม -> รหัสใน mfg.downtime_reason
        FROM    <<schema>>.<<stop_table>> src
        LEFT JOIN (VALUES
                    (N'<<รหัสเดิม 1>>', N'BD-MECH'),
                    (N'<<รหัสเดิม 2>>', N'SETUP')
                  ) map (old_code, reason_code) ON map.old_code = src.<<stop_reason_col>>
        WHERE   EXISTS (SELECT 1 FROM mfg.machine m WHERE m.machine_id = src.<<machine_col>>)   -- ข้ามเครื่องที่ยังไม่มี
          AND   (src.<<stop_end_col>> IS NULL OR src.<<stop_end_col>> > src.<<stop_start_col>>)    -- ข้ามเวลาที่ผิด
          AND  (    src.<<stop_start_col>> >= @since
                OR  src.<<stop_end_col>> IS NULL
                OR  src.<<stop_end_col>> >= @since
                -- การหยุดที่ยังเปิดค้างใน mfg (เริ่มก่อนช่วงที่ดึง) ต้องดึงมาปิดด้วย
                OR  EXISTS (SELECT 1 FROM mfg.downtime_event o
                            WHERE o.source_ref = CAST(src.<<stop_id_col>> AS NVARCHAR(100)) AND o.end_ts IS NULL))
    ) AS s
    ON  t.source_ref = s.source_ref
    WHEN MATCHED THEN
        UPDATE SET end_ts = s.end_ts, reason_code = ISNULL(t.reason_code, s.reason_code), updated_at = @now
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (machine_id, start_ts, end_ts, reason_code, source, source_ref)
        VALUES (s.machine_id, s.start_ts, s.end_ts, s.reason_code, N'IMPORT', s.source_ref);

    COMMIT TRANSACTION;
END;

END-TEMPLATE  <<< ลบบรรทัดนี้ทั้งบรรทัดด้วย */
GO

-- นำเข้าแผนการผลิต / ยอดผลิต / เครื่องหยุด / ข้อมูลหลัก จาก Excel: ดู 07_excel_import.sql

SET NOEXEC OFF;
GO
