# Derived Helpers

ไฟล์ใน folder นี้เป็น helper/cache ที่สร้างจาก public source data เพื่อช่วยตรวจสอบและทำ reconciliation เท่านั้น ไม่ใช่ official tables ที่กรรมการให้มา

## sales_deposit_batch_reconciliation.csv

- เดิมชื่อ `FACT_SALES_DEPOSIT_BATCH.csv` แต่เปลี่ยนชื่อเพื่อไม่ให้สับสนกับ official `FACT_*` table
- กรรมการยืนยันว่า `FACT_SALES_DEPOSIT_BATCH` ถูกลบออกจาก bundle โดยตั้งใจ จึงไม่ควรสร้างกลับมาเป็น official source table
- ไฟล์นี้ reconstruct จาก `FACT_SALES` และ cross-check กับ `FACT_BANK_TRANSACTION`
- ใช้สำหรับ QA/reconciliation/internal trace เท่านั้น
- เวลาเขียนคำตอบ final ให้อ้าง source จริงคือ:
  - `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_BANK_TRANSACTION.csv`
  - `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_SALES.csv`

