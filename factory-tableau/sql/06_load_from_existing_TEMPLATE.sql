/* =====================================================================
   06_load_from_existing_TEMPLATE.sql  —  แม่แบบ: ดึงข้อมูลจากตารางเดิมของโรงงานเข้า mfg

   ใช้เมื่อโรงงานมีตารางเก็บยอดผลิต/เครื่องหยุดอยู่แล้ว (จาก PLC, MES, โปรแกรมเดิม)
   แทนที่จะให้ระบบเดิมเขียนเข้า mfg โดยตรง ให้ตั้งเวลา (ทุก 15-60 นาที) รัน procedure นี้

   >>> ไฟล์นี้เป็นแม่แบบ ต้องแก้ชื่อตาราง/คอลัมน์ในเครื่องหมาย <<...>> ให้ตรงกับของจริงก่อน <<<
   ถ้าไม่แน่ใจ ส่งผลของคำสั่งนี้มาให้ช่วยแก้ได้ (ส่งแค่โครงสร้าง ไม่ต้องส่งข้อมูล):
       SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
       FROM INFORMATION_SCHEMA.COLUMNS ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;

   การตั้งเวลา:
     - SQL Server รุ่น Standard/Enterprise: ใช้ SQL Server Agent สร้าง Job รัน
         EXEC mfg.usp_load_from_existing;
     - SQL Server Express (ไม่มี Agent): ใช้ Windows Task Scheduler รันคำสั่ง
         sqlcmd -S <ชื่อเซิร์ฟเวอร์> -d FactoryBI -E -Q "EXEC mfg.usp_load_from_existing"
   ===================================================================== */

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
BEGIN
    RAISERROR(N'กรุณาเลือกฐานข้อมูลของโรงงาน (เช่น FactoryBI) ก่อนรันสคริปต์นี้', 16, 1);
    SET NOEXEC ON;
END
GO

/* BEGIN-TEMPLATE  <<< แก้ชื่อในเครื่องหมาย <<...>> ให้ครบ แล้วลบบรรทัดนี้ทั้งบรรทัด

CREATE OR ALTER PROCEDURE mfg.usp_load_from_existing
    @days_back INT = 3          -- ดึงย้อนหลังกี่วัน (ดึงซ้ำได้ ไม่เกิดข้อมูลซ้ำ)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @since DATETIME2(0) = DATEADD(DAY, -@days_back, (SELECT now_local FROM mfg.v_now));

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
        GROUP BY src.<<machine_col>>, DATEADD(HOUR, DATEDIFF(HOUR, 0, src.<<timestamp_col>>), 0), ISNULL(src.<<sku_col>>, N'UNKNOWN')
    ) AS s
    ON  t.machine_id = s.machine_id AND t.hour_start = s.hour_start AND t.sku = s.sku
    WHEN MATCHED AND (t.total_qty <> s.total_qty OR t.good_qty <> s.good_qty) THEN
        UPDATE SET total_qty = s.total_qty, good_qty = s.good_qty, source = N'IMPORT', updated_at = SYSDATETIME()
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (machine_id, hour_start, sku, total_qty, good_qty, source)
        VALUES (s.machine_id, s.hour_start, s.sku, s.total_qty, s.good_qty, N'IMPORT');

    -- 2) เครื่องหยุด: ต้องมีรหัสอ้างอิงจากระบบเดิม เพื่อไม่ให้ซ้ำเวลาดึงซ้ำ
    --    เพิ่มคอลัมน์ source_ref ครั้งแรกครั้งเดียว:
    --      ALTER TABLE mfg.downtime_event ADD source_ref NVARCHAR(100) NULL;
    --      CREATE UNIQUE INDEX UX_downtime_source_ref ON mfg.downtime_event (source_ref) WHERE source_ref IS NOT NULL;
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
        WHERE   src.<<stop_start_col>> >= @since OR src.<<stop_end_col>> IS NULL
    ) AS s
    ON  t.source_ref = s.source_ref
    WHEN MATCHED THEN
        UPDATE SET end_ts = s.end_ts, reason_code = ISNULL(t.reason_code, s.reason_code), updated_at = SYSDATETIME()
    WHEN NOT MATCHED BY TARGET THEN
        INSERT (machine_id, start_ts, end_ts, reason_code, source, source_ref)
        VALUES (s.machine_id, s.start_ts, s.end_ts, s.reason_code, N'IMPORT', s.source_ref);

    COMMIT TRANSACTION;
END;

END-TEMPLATE  <<< ลบบรรทัดนี้ทั้งบรรทัดด้วย */
GO

/* ---------------------------------------------------------------------
   นำเข้าแผนการผลิตจาก Excel (ทำทุกครั้งที่ฝ่ายวางแผนออกแผนใหม่)
   1) ใน Excel ทำคอลัมน์: prod_date | shift_code | machine_id | sku | plan_qty
   2) SSMS: คลิกขวาที่ฐานข้อมูล > Tasks > Import Flat File (บันทึก Excel เป็น CSV UTF-8 ก่อน)
      ตั้งชื่อตารางปลายทางว่า stg_plan (schema dbo)
   3) รันคำสั่งด้านล่าง แล้วลบ stg_plan ทิ้ง
   --------------------------------------------------------------------- */
/*
MERGE mfg.production_plan AS t
USING (
    SELECT CAST(prod_date AS DATE) AS prod_date, shift_code, machine_id, sku, SUM(CAST(plan_qty AS INT)) AS plan_qty
    FROM   dbo.stg_plan
    GROUP BY CAST(prod_date AS DATE), shift_code, machine_id, sku
) AS s
ON  t.prod_date = s.prod_date AND t.shift_code = s.shift_code AND t.machine_id = s.machine_id AND t.sku = s.sku
WHEN MATCHED THEN
    UPDATE SET plan_qty = s.plan_qty, source = N'EXCEL', updated_at = SYSDATETIME()
WHEN NOT MATCHED BY TARGET THEN
    INSERT (prod_date, shift_code, machine_id, sku, plan_qty, source)
    VALUES (s.prod_date, s.shift_code, s.machine_id, s.sku, s.plan_qty, N'EXCEL');

DROP TABLE dbo.stg_plan;
*/

SET NOEXEC OFF;
GO
