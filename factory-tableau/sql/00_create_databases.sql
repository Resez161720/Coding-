/* =====================================================================
   00_create_databases.sql
   สร้างฐานข้อมูล 2 ตัว
     - FactoryBI       : ฐานข้อมูลจริงของโรงงาน
     - FactoryBI_Demo  : ฐานข้อมูลทดลอง (ใส่ข้อมูลตัวอย่าง ลบทิ้งได้ทั้งก้อน)
   รันใน SSMS ได้เลย (ต้องใช้สิทธิ์สร้างฐานข้อมูล เช่น sysadmin หรือ dbcreator)
   รันซ้ำได้ ไม่ลบของเดิม
   ===================================================================== */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF DB_ID(N'FactoryBI') IS NULL
    CREATE DATABASE FactoryBI;
GO

IF DB_ID(N'FactoryBI_Demo') IS NULL
    CREATE DATABASE FactoryBI_Demo;
GO

PRINT N'สร้างฐานข้อมูลเรียบร้อย: FactoryBI, FactoryBI_Demo';
GO
