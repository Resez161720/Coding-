"""ข้อมูลสำหรับโหมดทดลอง (demo): ใบสั่งงานสมมติในจอเขียวจำลอง และตัวอย่างข้อมูลจากเครื่องยิง"""

from .driver.fake import FakeGreenScreen, WorkOrder

DEMO_WORK_ORDERS = [
    WorkOrder("OCT26AA", "DEMO-1001", "DEMO STACK A", 63, 400000, "0010", "STAMPING 1"),
    WorkOrder("OCT26BB", "DEMO-2002", "DEMO STATOR B", 203, 120000, "0187", "STAMPING+L 100%"),
    WorkOrder("OCT26CC", "DEMO-3003", "DEMO CORE C", 960, 50000, "0278", "STACKING"),
]

DEMO_SCANS = "\n".join([
    "MC-A1", "OCT26AA", "OP26ZZ000101", "OF26ZZ10000201", "DIE.4", "EMP-T0001",
    "CT-M01", "CMD-FULL", "CT-M02", "CMD-FULL",
    "MC-A2", "OCT26BB", "OP26ZZ000102", "OF26ZZ10000202", "DIE.2", "EMP-T0002",
    "CT-M03", "NUM-1", "NUM-5", "NUM-0", "CMD-END", "CMD-NG", "NUM-3", "CMD-END",
    "MC-W1", "OCT26CC", "OP26ZZ000103", "OF26ZZ10000203", "DIE.7", "EMP-T0003",
    "CT-W01", "CMD-FULL",
])


def demo_driver():
    return FakeGreenScreen([WorkOrder(**vars(wo)) for wo in DEMO_WORK_ORDERS], user_name="DEMO USER")
