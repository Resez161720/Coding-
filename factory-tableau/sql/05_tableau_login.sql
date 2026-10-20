/* =====================================================================
   05_tableau_login.sql  —  สร้างผู้ใช้ "อ่านอย่างเดียว" ให้ Tableau / Tableau Bridge

   - ผู้ใช้นี้อ่านได้เฉพาะ view ใน schema rpt (แก้ไข/ลบข้อมูลไม่ได้ และมองไม่เห็นตารางใน mfg)
   - ต้องเปิด SQL Server ให้ login แบบ SQL Server authentication ได้ (Mixed Mode) — ดูขั้นตอนใน README

   วิธีรัน:
     1) เลือกฐานข้อมูลที่จะให้ Tableau อ่าน (เช่น FactoryBI หรือ FactoryBI_Demo)
     2) แก้รหัสผ่านในบรรทัด @password ด้านล่าง (ยาว 12 ตัวขึ้นไป มีตัวใหญ่ ตัวเล็ก ตัวเลข สัญลักษณ์)
     3) Execute — ถ้าจะให้อ่านอีกฐานข้อมูล ให้เลือกฐานข้อมูลนั้นแล้วรันซ้ำ (ใช้รหัสผ่านเดิม)
   ===================================================================== */

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
BEGIN
    RAISERROR(N'กรุณาเลือกฐานข้อมูลของโรงงาน (เช่น FactoryBI) ก่อนรันสคริปต์นี้', 16, 1);
    SET NOEXEC ON;
END
GO

DECLARE @login    SYSNAME       = N'tableau_reader';
DECLARE @password NVARCHAR(128) = N'<<เปลี่ยนเป็นรหัสผ่านใหม่>>';   -- <<< แก้ตรงนี้
DECLARE @sql      NVARCHAR(MAX);

IF @password LIKE N'<<%'
BEGIN
    RAISERROR(N'กรุณาแก้ @password เป็นรหัสผ่านใหม่ก่อนรัน', 16, 1);
    RETURN;
END;

-- 1) login ระดับเซิร์ฟเวอร์ (สร้างครั้งเดียว)
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = @login)
BEGIN
    SET @sql = N'CREATE LOGIN ' + QUOTENAME(@login)
             + N' WITH PASSWORD = ' + QUOTENAME(@password, N'''')
             + N', DEFAULT_DATABASE = ' + QUOTENAME(DB_NAME())
             + N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF;';
    EXEC sys.sp_executesql @sql;
    PRINT N'สร้าง login tableau_reader แล้ว';
END
ELSE
    PRINT N'มี login tableau_reader อยู่แล้ว (ไม่ได้เปลี่ยนรหัสผ่าน)';

-- 2) user ในฐานข้อมูลนี้
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @login)
BEGIN
    SET @sql = N'CREATE USER ' + QUOTENAME(@login) + N' FOR LOGIN ' + QUOTENAME(@login) + N' WITH DEFAULT_SCHEMA = rpt;';
    EXEC sys.sp_executesql @sql;
END;

-- 3) ให้อ่านได้เฉพาะ schema rpt
SET @sql = N'GRANT SELECT ON SCHEMA::rpt TO ' + QUOTENAME(@login) + N';';
EXEC sys.sp_executesql @sql;

PRINT CONCAT(N'ให้สิทธิ์ ', @login, N' อ่าน schema rpt ในฐานข้อมูล ', DB_NAME(), N' เรียบร้อย');
GO
SET NOEXEC OFF;
GO
