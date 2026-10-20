/* =====================================================================
   01_schema.sql  —  ตารางเก็บข้อมูล (schema mfg)

   วิธีรัน: ใน SSMS เลือกฐานข้อมูล (FactoryBI หรือ FactoryBI_Demo) ที่ช่อง
            Available Databases ก่อน แล้วกด Execute
   รันซ้ำได้: สร้างเฉพาะตารางที่ยังไม่มี ไม่ลบหรือแก้ข้อมูลเดิม
   ต้องใช้ SQL Server 2016 SP1 ขึ้นไป

   หลักการเก็บเวลา: ทุกคอลัมน์วันเวลาเก็บเป็น "เวลาไทย" (UTC+7) ไม่ใช่ UTC
   ===================================================================== */

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
BEGIN
    RAISERROR(N'กรุณาเลือกฐานข้อมูลของโรงงาน (เช่น FactoryBI) ก่อนรันสคริปต์นี้', 16, 1);
    SET NOEXEC ON;
END
GO

IF SCHEMA_ID(N'mfg') IS NULL EXEC (N'CREATE SCHEMA mfg AUTHORIZATION dbo');
GO
IF SCHEMA_ID(N'rpt') IS NULL EXEC (N'CREATE SCHEMA rpt AUTHORIZATION dbo');
GO

/* ---------------------------------------------------------------------
   ข้อมูลหลัก (Master)
   --------------------------------------------------------------------- */

-- เครื่องจักร
IF OBJECT_ID(N'mfg.machine', N'U') IS NULL
CREATE TABLE mfg.machine (
    machine_id      NVARCHAR(20)  NOT NULL CONSTRAINT PK_machine PRIMARY KEY,
    machine_name    NVARCHAR(100) NOT NULL,
    line_id         NVARCHAR(20)  NOT NULL,              -- ไลน์/แผนก
    machine_type    NVARCHAR(50)  NULL,                  -- เช่น ฉีด, ปั๊ม, CNC
    is_active       BIT           NOT NULL CONSTRAINT DF_machine_active DEFAULT (1),  -- 0 = เลิกใช้/จอด
    is_bottleneck   BIT           NOT NULL CONSTRAINT DF_machine_bn DEFAULT (0),      -- 1 = เครื่องคอขวดที่รู้อยู่แล้ว
    sort_order      INT           NULL
);
GO

-- สินค้า
IF OBJECT_ID(N'mfg.product', N'U') IS NULL
CREATE TABLE mfg.product (
    sku             NVARCHAR(40)  NOT NULL CONSTRAINT PK_product PRIMARY KEY,
    product_name    NVARCHAR(200) NOT NULL,
    product_family  NVARCHAR(100) NULL
);
GO

-- รอบเวลามาตรฐาน (Ideal cycle time) ต่อสินค้า x เครื่อง
-- ใช้ค่าที่ "เร็วที่สุดที่เคยทำได้จริงอย่างสม่ำเสมอ" ไม่ใช่ค่าจากแคตตาล็อกเครื่อง
IF OBJECT_ID(N'mfg.std_cycle_time', N'U') IS NULL
CREATE TABLE mfg.std_cycle_time (
    machine_id      NVARCHAR(20)  NOT NULL CONSTRAINT FK_ct_machine REFERENCES mfg.machine (machine_id),
    sku             NVARCHAR(40)  NOT NULL,
    ideal_ct_sec    DECIMAL(10,3) NOT NULL CONSTRAINT CK_ct_positive CHECK (ideal_ct_sec > 0),  -- วินาทีต่อชิ้น
    CONSTRAINT PK_std_cycle_time PRIMARY KEY (machine_id, sku)
);
GO

-- รหัสสาเหตุเครื่องหยุด
-- loss_category:
--   PLANNED     = หยุดตามแผน (PM ตามแผน, ไม่มีออร์เดอร์, ประชุม/อบรม) -> ไม่นับเป็นความสูญเสีย
--   BREAKDOWN   = เครื่องเสีย
--   SETUP       = เปลี่ยนรุ่น/ตั้งเครื่อง (นับเป็นความสูญเสีย ตามมาตรฐาน OEE)
--   MINOR_STOP  = หยุดสั้น ๆ
--   MATERIAL    = รอวัตถุดิบ/รอชิ้นงาน
--   MANPOWER    = รอคน/ไม่มีคนคุม
--   QUALITY     = หยุดเพราะปัญหาคุณภาพ
--   OTHER       = อื่น ๆ
-- หมายเหตุ: "พักเบรก" ไม่ต้องมีรหัส เพราะระบบหักเวลาพักออกให้เองจากตารางกะ
IF OBJECT_ID(N'mfg.downtime_reason', N'U') IS NULL
CREATE TABLE mfg.downtime_reason (
    reason_code     NVARCHAR(20)  NOT NULL CONSTRAINT PK_downtime_reason PRIMARY KEY,
    reason_name_th  NVARCHAR(100) NOT NULL,
    reason_name_en  NVARCHAR(100) NULL,
    loss_category   NVARCHAR(20)  NOT NULL CONSTRAINT CK_reason_category CHECK (loss_category IN
                        (N'PLANNED', N'BREAKDOWN', N'SETUP', N'MINOR_STOP', N'MATERIAL', N'MANPOWER', N'QUALITY', N'OTHER')),
    responsible_dept NVARCHAR(50) NULL,                  -- ฝ่ายที่รับผิดชอบแก้ไข
    is_active       BIT           NOT NULL CONSTRAINT DF_reason_active DEFAULT (1),
    sort_order      INT           NULL
);
GO

-- วันหยุด (ใช้ตอนสร้างปฏิทินกะ)
IF OBJECT_ID(N'mfg.holiday', N'U') IS NULL
CREATE TABLE mfg.holiday (
    holiday_date    DATE          NOT NULL CONSTRAINT PK_holiday PRIMARY KEY,
    holiday_name    NVARCHAR(100) NOT NULL
);
GO

/* ---------------------------------------------------------------------
   กะทำงาน
   --------------------------------------------------------------------- */

-- นิยามกะ: เวลาเริ่มต้องตรงชั่วโมงพอดี (เช่น 08:00) และความยาวกะเป็นชั่วโมงเต็ม
-- start_day_offset: กะที่เริ่มหลังเที่ยงคืนแต่นับเป็นวันผลิตของเมื่อวาน ให้ใส่ 1
IF OBJECT_ID(N'mfg.shift_definition', N'U') IS NULL
CREATE TABLE mfg.shift_definition (
    shift_code       NVARCHAR(10) NOT NULL CONSTRAINT PK_shift_definition PRIMARY KEY,
    shift_name_th    NVARCHAR(50) NOT NULL,
    start_time       TIME(0)      NOT NULL,
    duration_min     INT          NOT NULL,
    start_day_offset TINYINT      NOT NULL CONSTRAINT DF_shift_offset DEFAULT (0),
    sort_order       INT          NOT NULL CONSTRAINT DF_shift_sort DEFAULT (1),
    is_active        BIT          NOT NULL CONSTRAINT DF_shift_active DEFAULT (1),
    CONSTRAINT CK_shift_start_on_hour CHECK (DATEPART(MINUTE, start_time) = 0 AND DATEPART(SECOND, start_time) = 0),
    CONSTRAINT CK_shift_duration CHECK (duration_min BETWEEN 60 AND 1440 AND duration_min % 60 = 0),
    CONSTRAINT CK_shift_offset CHECK (start_day_offset IN (0, 1))
);
GO

-- เวลาพักในแต่ละกะ: offset_min = เริ่มพักหลังเริ่มกะกี่นาที
IF OBJECT_ID(N'mfg.shift_break_definition', N'U') IS NULL
CREATE TABLE mfg.shift_break_definition (
    shift_code      NVARCHAR(10) NOT NULL CONSTRAINT FK_break_shift REFERENCES mfg.shift_definition (shift_code),
    break_no        TINYINT      NOT NULL,
    offset_min      INT          NOT NULL CONSTRAINT CK_break_offset CHECK (offset_min >= 0),
    break_min       INT          NOT NULL CONSTRAINT CK_break_len CHECK (break_min > 0),
    CONSTRAINT PK_shift_break_definition PRIMARY KEY (shift_code, break_no)
);
GO

-- ปฏิทินกะ: 1 แถว = 1 กะ ใน 1 วันผลิต (สร้างด้วย mfg.usp_build_shift_calendar)
-- แก้ is_working เองได้ เช่น วันที่ไม่ทำงาน หรือวันที่เพิ่มกะ
IF OBJECT_ID(N'mfg.shift_calendar', N'U') IS NULL
CREATE TABLE mfg.shift_calendar (
    prod_date       DATE          NOT NULL,             -- วันผลิต (กะดึกที่ข้ามเที่ยงคืนยังเป็นวันเดียวกับวันที่เริ่มกะ)
    shift_code      NVARCHAR(10)  NOT NULL CONSTRAINT FK_cal_shift REFERENCES mfg.shift_definition (shift_code),
    shift_start     DATETIME2(0)  NOT NULL,
    shift_end       DATETIME2(0)  NOT NULL,
    is_working      BIT           NOT NULL CONSTRAINT DF_cal_working DEFAULT (1),  -- 0 = วันหยุด/ไม่มีกะนี้ตามปกติ
    note            NVARCHAR(200) NULL,
    CONSTRAINT PK_shift_calendar PRIMARY KEY (prod_date, shift_code),
    CONSTRAINT CK_cal_range CHECK (shift_end > shift_start),
    CONSTRAINT CK_cal_on_hour CHECK (DATEPART(MINUTE, shift_start) = 0 AND DATEPART(SECOND, shift_start) = 0
                                 AND DATEPART(MINUTE, shift_end) = 0 AND DATEPART(SECOND, shift_end) = 0)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_shift_calendar_start' AND object_id = OBJECT_ID(N'mfg.shift_calendar'))
    CREATE UNIQUE INDEX UX_shift_calendar_start ON mfg.shift_calendar (shift_start) INCLUDE (shift_end, prod_date, shift_code);
GO

/* ---------------------------------------------------------------------
   ข้อมูลการผลิต (Fact)
   --------------------------------------------------------------------- */

-- แผนการผลิต: 1 แถว = เครื่อง x วันผลิต x กะ x สินค้า
IF OBJECT_ID(N'mfg.production_plan', N'U') IS NULL
CREATE TABLE mfg.production_plan (
    prod_date       DATE          NOT NULL,
    shift_code      NVARCHAR(10)  NOT NULL,
    machine_id      NVARCHAR(20)  NOT NULL CONSTRAINT FK_plan_machine REFERENCES mfg.machine (machine_id),
    sku             NVARCHAR(40)  NOT NULL,
    plan_qty        INT           NOT NULL CONSTRAINT CK_plan_qty CHECK (plan_qty >= 0),
    source          NVARCHAR(20)  NOT NULL CONSTRAINT DF_plan_source DEFAULT (N'MANUAL'),
    updated_at      DATETIME2(0)  NOT NULL CONSTRAINT DF_plan_updated DEFAULT (SYSDATETIME()),
    CONSTRAINT PK_production_plan PRIMARY KEY (prod_date, shift_code, machine_id, sku),
    CONSTRAINT FK_plan_calendar FOREIGN KEY (prod_date, shift_code) REFERENCES mfg.shift_calendar (prod_date, shift_code)
);
GO

-- ยอดผลิตรายชั่วโมง: 1 แถว = เครื่อง x ชั่วโมง x สินค้า
-- hour_start ต้องเป็นต้นชั่วโมงพอดี เช่น 2026-10-20 09:00:00 (นับชิ้นที่ผลิตช่วง 09:00-09:59)
IF OBJECT_ID(N'mfg.production_hour', N'U') IS NULL
CREATE TABLE mfg.production_hour (
    machine_id      NVARCHAR(20)  NOT NULL CONSTRAINT FK_prod_machine REFERENCES mfg.machine (machine_id),
    hour_start      DATETIME2(0)  NOT NULL,
    sku             NVARCHAR(40)  NOT NULL,
    total_qty       INT           NOT NULL CONSTRAINT CK_prod_total CHECK (total_qty >= 0),   -- ผลิตทั้งหมด (ดี+เสีย)
    good_qty        INT           NOT NULL CONSTRAINT CK_prod_good CHECK (good_qty >= 0),     -- ของดี
    source          NVARCHAR(20)  NOT NULL CONSTRAINT DF_prod_source DEFAULT (N'MANUAL'),     -- PLC / FORM / IMPORT / MANUAL
    updated_at      DATETIME2(0)  NOT NULL CONSTRAINT DF_prod_updated DEFAULT (SYSDATETIME()),
    CONSTRAINT PK_production_hour PRIMARY KEY (machine_id, hour_start, sku),
    CONSTRAINT CK_prod_good_le_total CHECK (good_qty <= total_qty),
    CONSTRAINT CK_prod_on_hour CHECK (DATEPART(MINUTE, hour_start) = 0 AND DATEPART(SECOND, hour_start) = 0)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_production_hour_time' AND object_id = OBJECT_ID(N'mfg.production_hour'))
    CREATE INDEX IX_production_hour_time ON mfg.production_hour (hour_start) INCLUDE (machine_id, sku, total_qty, good_qty);
GO

-- เหตุการณ์เครื่องหยุด: 1 แถว = หยุด 1 ครั้ง
-- end_ts ว่าง (NULL) = ยังหยุดอยู่ ; reason_code ว่าง = ยังไม่ได้ระบุสาเหตุ
IF OBJECT_ID(N'mfg.downtime_event', N'U') IS NULL
CREATE TABLE mfg.downtime_event (
    event_id        BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_downtime_event PRIMARY KEY,
    machine_id      NVARCHAR(20)  NOT NULL CONSTRAINT FK_dt_machine REFERENCES mfg.machine (machine_id),
    start_ts        DATETIME2(0)  NOT NULL,
    end_ts          DATETIME2(0)  NULL,
    reason_code     NVARCHAR(20)  NULL CONSTRAINT FK_dt_reason REFERENCES mfg.downtime_reason (reason_code),
    note            NVARCHAR(400) NULL,
    source          NVARCHAR(20)  NOT NULL CONSTRAINT DF_dt_source DEFAULT (N'MANUAL'),
    created_at      DATETIME2(0)  NOT NULL CONSTRAINT DF_dt_created DEFAULT (SYSDATETIME()),
    updated_at      DATETIME2(0)  NOT NULL CONSTRAINT DF_dt_updated DEFAULT (SYSDATETIME()),
    CONSTRAINT CK_dt_range CHECK (end_ts IS NULL OR end_ts > start_ts)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_downtime_event_machine_time' AND object_id = OBJECT_ID(N'mfg.downtime_event'))
    CREATE INDEX IX_downtime_event_machine_time ON mfg.downtime_event (machine_id, start_ts) INCLUDE (end_ts, reason_code);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_downtime_event_time' AND object_id = OBJECT_ID(N'mfg.downtime_event'))
    CREATE INDEX IX_downtime_event_time ON mfg.downtime_event (start_ts) INCLUDE (machine_id, end_ts, reason_code);
GO

PRINT N'01_schema.sql เสร็จ: สร้างตารางใน schema mfg แล้ว';
GO
SET NOEXEC OFF;
GO
