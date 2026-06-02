# FahMai Tables: ประเด็นผิดปกติในข้อมูลและคำถามถึงกรรมการ

## สรุปสำหรับตัดสินใจ

ตรวจ folder `super-ai-engineer-season-6-fah-mai-the-finale/tables` แล้วพบว่าโครงสร้างหลักค่อนข้างดี: มี 31 CSVs จริงตาม README และ primary key คอลัมน์แรกของทุกไฟล์ unique ไม่มี null/duplicate key rows

แต่มีหลายจุดที่ควรถามกรรมการก่อนทำ private pipeline เพราะมีผลกับ join logic, bitemporal/date resolution, reconciliation, และคำตอบ leaderboard:

- `FACT_BANK_TRANSACTION.related_entity_table` อ้างถึง `FACT_SALES_DEPOSIT_BATCH` จำนวน 28,279 rows แต่ไม่มี CSV/table ชื่อนี้ใน `tables`
- fact tables ส่วนใหญ่มี `effective_date` ว่าง 100% แต่มี `as_of_date = 2026-01-15` ทุกแถว ต้องถามว่า bitemporal columns ต้องใช้ยังไง
- policy และ vendor contract versions มี boundary แบบ `end_date == next effective_date` ต้องถามว่า `end_date` inclusive หรือ exclusive
- `FACT_VENDOR_PAYMENT` ของ `V-018` มี 8 rows ที่ `business_event_date = 2025-03-31` แต่ contract version เริ่ม `2025-04-01`; ถ้าใช้ `posting_date` จะ valid
- มี known data-quality artifacts ที่น่าจะตั้งใจ เช่น duplicate PayWise invoice, phantom promo redemption, และ transfer IDs ใน inventory movement
- บาง fields ต้อง parse อย่างระวัง เช่น `FACT_RETURN.line_item_id` เป็น large numeric ID ที่ pandas อ่านเป็น float แล้วทำให้ string join พัง

ข้อสรุปปฏิบัติ: อย่า assume ว่าทุก reference join กลับ physical CSV ได้, อ่าน ID columns เป็น string-safe, และต้อง lock date-resolution policy กับกรรมการก่อนตอบคำถามที่เกี่ยวกับ policy/contract/as-of date

## รายการตาราง

มี CSV ทั้งหมด 31 ไฟล์:

| ตาราง | จำนวนแถว | หมายเหตุ |
|---|---:|---|
| `DIM_BANK_ACCOUNT.csv` | 14 | dimension ของบัญชีธนาคาร |
| `DIM_BRANCH.csv` | 11 | 9 branch + 1 hq + 1 remote |
| `dim_care_plus_sku_tier.csv` | 2 | filename เป็น lowercase `dim_*` |
| `DIM_CUSTOMER.csv` | 30,000 | dimension ของลูกค้า |
| `DIM_DATE.csv` | 731 | 2024-01-01 ถึง 2025-12-31 |
| `DIM_DEPARTMENT.csv` | 9 | dimension ของแผนก |
| `DIM_EMPLOYEE.csv` | 600 | dimension ของพนักงาน |
| `DIM_POLICY_VERSION.csv` | 12 | ตาราง policy effective/end-date |
| `DIM_POSITION_LEVEL.csv` | 6 | dimension ของระดับตำแหน่ง |
| `DIM_PRODUCT.csv` | 110 | dimension ของ product/SKU |
| `dim_product_recall_history.csv` | 3 | filename เป็น lowercase `dim_*` |
| `DIM_PROMO_CAMPAIGN.csv` | 7 | ช่วง campaign |
| `dim_promo_mechanic.csv` | 8 | filename เป็น lowercase `dim_*` |
| `dim_signing_authority_ladder.csv` | 7 | filename เป็น lowercase `dim_*` |
| `DIM_VENDOR.csv` | 6 | dimension ของ vendor |
| `DIM_VENDOR_CONTRACT_VERSION.csv` | 22 | ตาราง effective/end-date ของ vendor contract |
| `FACT_BANK_TRANSACTION.csv` | 65,334 | bank transactions และ dynamic related entities |
| `FACT_CS_INTERACTION.csv` | 14,368 | CS interactions |
| `FACT_INVENTORY_MONTHLY_SNAPSHOT.csv` | 26,220 | inventory snapshots |
| `FACT_INVENTORY_MOVEMENT.csv` | 310,827 | inventory movements |
| `FACT_LOYALTY_LEDGER.csv` | 118,857 | loyalty points ledger |
| `FACT_PAYROLL.csv` | 14,400 | payroll facts |
| `FACT_PROMO_REDEMPTION.csv` | 1,583 | promo redemption facts |
| `FACT_REFUND_PAID.csv` | 7,134 | refund payment facts |
| `FACT_RETURN.csv` | 7,144 | returns |
| `FACT_SALES.csv` | 117,105 | sales header facts |
| `FACT_SALES_LINE_ITEM.csv` | 309,129 | sales line items |
| `FACT_SHIPPING.csv` | 23,182 | shipping facts |
| `FACT_VENDOR_PAYMENT.csv` | 809 | vendor payments |
| `FACT_WARRANTY_CLAIM.csv` | 3,973 | warranty claims |
| `T2_DOC_INVENTORY.csv` | 81 | document inventory |

จุดแปลกเรื่องชื่อไฟล์: มี dimension-like files 4 ไฟล์ที่ใช้ lowercase `dim_*` ในขณะที่ไฟล์อื่นใช้ uppercase `DIM_*` เรื่องนี้ไม่เป็นปัญหาบน Windows แต่อาจมีผลบน Linux/case-sensitive paths ถ้า code สร้าง filenames แบบ mechanical

ผลตรวจ primary key: คอลัมน์แรกของทุก CSV unique และไม่เป็น null ไม่พบ duplicate primary-key rows

## ประเด็นสำคัญที่ควรถามก่อน

### 1. Dynamic bank references ชี้ไป table ที่ไม่มี CSV จริง

`FACT_BANK_TRANSACTION.related_entity_table` มีค่า:

| related_entity_table | จำนวนแถว |
|---|---:|
| `FACT_SALES_DEPOSIT_BATCH` | 28,279 |
| `FACT_PAYROLL` | 14,400 |
| `FACT_SALES` | 13,313 |
| `FACT_REFUND_PAID` | 7,134 |
| `FACT_LOYALTY_LEDGER` | 1,255 |
| `FACT_VENDOR_PAYMENT` | 809 |
| null | 144 |

Physical table references อื่นๆ ที่ตรวจแล้ว resolve กับ CSV ที่มีอยู่ได้ แต่ `FACT_SALES_DEPOSIT_BATCH` ไม่มี CSV ใน `tables`

ตีความที่เป็นไปได้: `FACT_SALES_DEPOSIT_BATCH` อาจเป็น virtual aggregate id เช่น `branch|date|payment_method` ไม่ใช่ physical fact table

คำถามถึงกรรมการ: **`FACT_SALES_DEPOSIT_BATCH` เป็น intentionally virtual/derived entity ใช่ไหม? ถ้าคำถามอ้างถึง entity นี้ ทีมควร reconstruct จาก `FACT_SALES`, bank transactions, หรือ logs?**

### 2. Bitemporal columns ยังอธิบายตัวเองไม่พอ

Fact tables ส่วนใหญ่มี:

- `business_event_date`
- `posting_date`
- `effective_date`
- `as_of_date`

รูปแบบที่พบ:

- `effective_date` เป็น null ใน fact tables ที่ตรวจ และมักว่าง 100%
- `as_of_date` เป็น `2026-01-15` ทั้งหมด ตรงกับ README release as-of date
- dimension/version tables เช่น `DIM_POLICY_VERSION` และ `DIM_VENDOR_CONTRACT_VERSION` มี `effective_date`/`end_date` ที่มีความหมายจริง

ผลกระทบ: ถ้าคำถามถาม "as of event date" หรือเกี่ยวกับ bitemporal logic ยังไม่ชัดว่าต้องใช้ `business_event_date`, `posting_date`, `effective_date`, หรือ `as_of_date` สำหรับ table family ใด

คำถามถึงกรรมการ: **สำหรับ fact rows ควร ignore `effective_date` null หรือไม่? `as_of_date = 2026-01-15` เป็นแค่ bundle release snapshot date ใช่ไหม? Temporal joins ควรใช้ `business_event_date` หรือ `posting_date`?**

### 3. ต้องถามว่า policy/contract date boundaries เป็น inclusive หรือ exclusive

Versioned tables มีช่วงวันที่ติดกันโดย `end_date` เท่ากับ `effective_date` ของ row ถัดไป

ตัวอย่าง:

- `DIM_POLICY_VERSION.return_window_days`: `2024-01-01` ถึง `2025-03-01`, แล้ว `2025-03-01` เป็นต้นไป
- `DIM_VENDOR_CONTRACT_VERSION.V-013`: `2025-04-01` ถึง `2025-07-01`, แล้ว `2025-07-01` ถึง `2025-10-01`

ผลกระทบ: คำตอบบน boundary date จะต่างกันถ้า `end_date` inclusive หรือ exclusive

ค่า default ที่แนะนำระหว่างรอคำตอบ: ใช้ช่วงแบบ half-open คือ `effective_date <= date < end_date`, และ null `end_date` หมายถึง open-ended

คำถามถึงกรรมการ: **Version rows เป็น half-open (`effective_date <= date < end_date`) หรือ `end_date` inclusive?**

### 4. Vendor payment ของ `V-018` มี contract-date mismatch

`FACT_VENDOR_PAYMENT` มี 8 rows ของ `V-018` ที่:

- `business_event_date = 2025-03-31`
- `vendor_contract_version_id = 20`
- contract version 20 มี `effective_date = 2025-04-01`
- `posting_date` อยู่ใน April 2025 ดังนั้น rows จะ valid ถ้า contract resolution ใช้ `posting_date`

นี่เป็น ambiguity สำคัญ เพราะคำถามเรื่อง contract version อาจต้องหา contract ที่ถูกต้องตาม event time

คำถามถึงกรรมการ: **สำหรับ `FACT_VENDOR_PAYMENT.vendor_contract_version_id` ควรตรวจ validity ด้วย `business_event_date`, `posting_date`, `request_date`, หรือยึด explicit `vendor_contract_version_id` โดยไม่สนวันที่?**

### 5. `FACT_RETURN.line_item_id` ต้องอ่านเป็น string-safe integer

`FACT_RETURN.line_item_id` ดูเป็น numeric ถ้าอ่านด้วย pandas default inference จะกลายเป็น float/scientific notation และ exact string joins กับ `FACT_SALES_LINE_ITEM.line_item_id` จะ fail เพราะค่าเป็นแบบ `1095040358832.0`

สิ่งที่พบ:

- Direct string comparison หลังอ่านด้วย pandas default: 0 matches
- แปลง return `line_item_id` เป็น integer string ก่อน: 7,080/7,080 non-null values match `FACT_SALES_LINE_ITEM.line_item_id`
- Returns ทั้งหมด 7,144 rows สามารถ associate กับ sales line candidate อย่างน้อยหนึ่งรายการด้วย `original_txn_id + sku_id`

ผลกระทบ: agents/tools ที่ infer numeric IDs อาจสรุปผิดว่า foreign key fail

คำถามถึงกรรมการ: **ID-like numeric columns ทั้งหมดควรถูก treat เป็น opaque strings ใช่ไหม แม้ CSV parsers จะ infer เป็นตัวเลข?**

## Data-quality artifacts ที่น่าจะตั้งใจ

ประเด็นเหล่านี้ดูเหมือน intentional business/data-quality cases ไม่ควรรีบตีว่าเป็น dataset bugs

### 1. Duplicate PayWise invoice

`FACT_VENDOR_PAYMENT` มี duplicate invoice group หนึ่งกลุ่ม:

| vendor_id | vendor_invoice_id | จำนวนแถว |
|---|---|---:|
| `V-013` | `PW-INV-2568-04823` | 2 |

สอดคล้องกับ benchmark story เรื่อง duplicate invoices around schema cutover

คำถามถึงกรรมการ: **ถ้ามี duplicate invoice rows ควร list ทั้งสอง rows เว้นแต่คำถามระบุว่าให้ canonical/deduped result ใช่ไหม?**

### 2. Phantom promo redemptions

`FACT_PROMO_REDEMPTION` มี duplicated `txn_id` groups 4 กลุ่ม โดยแต่ละกลุ่มปรากฏข้าม `app,online` channels ใต้ `SF-LAUNCH-2568`:

| txn_id | Channels | Campaign |
|---|---|---|
| `TXN-202507-15018876` | `app,online` | `SF-LAUNCH-2568` |
| `TXN-202507-21020698` | `app,online` | `SF-LAUNCH-2568` |
| `TXN-202507-29013193` | `app,online` | `SF-LAUNCH-2568` |
| `TXN-202507-31015960` | `app,online` | `SF-LAUNCH-2568` |

คำถามถึงกรรมการ: **เมื่อคำถามถาม promo totals ควรรวม raw rows หรือ dedupe phantom redemptions เฉพาะเมื่อ prompt ถามเรื่อง phantom/double-logging handling?**

### 3. Inventory transfer IDs ไม่ใช่ sales transactions

`FACT_INVENTORY_MOVEMENT.related_txn_id` มี `XFER-*` ids:

- 2,400 distinct `XFER-*` ids
- 4,800 rows total
- จับคู่พอดีเป็น `transfer_out` และ `transfer_in`
- ค่าเหล่านี้ไม่มีใน `FACT_SALES.txn_id`

ตีความที่เป็นไปได้: `related_txn_id` เป็น polymorphic field: sales movements ชี้ไป `FACT_SALES`, ส่วน transfer movements ชี้ไป transfer batch ids

คำถามถึงกรรมการ: **`FACT_INVENTORY_MOVEMENT.related_txn_id` เป็น polymorphic ใช่ไหม? ควร treat `XFER-*` เป็น internal transfer ids ไม่ใช่ missing sales FKs ใช่ไหม?**

## จุดแปลกใน dimensions/tables

### `DIM_DATE` holiday fields ว่าง

`DIM_DATE` มี `is_thai_public_holiday` และ `holiday_name` แต่:

- `is_thai_public_holiday = True`: 0 rows
- `holiday_name` non-null: 0 rows

คำถามถึงกรรมการ: **Holiday logic ควร ignore `DIM_DATE` holiday columns หรือ holidays ถูก omit จาก public bundle โดยตั้งใจ?**

### `DIM_BRANCH.employee_headcount_share_pct` รวมได้ 0.92

`DIM_BRANCH.traffic_share_pct` รวมได้ประมาณ 1.0 แต่ `employee_headcount_share_pct` รวมได้ประมาณ 0.92

ตีความที่เป็นไปได้:

- 8% ที่เหลือเป็น non-branch/corporate employees ที่ไม่ได้ model เป็น branch share
- column นี้เป็น approximate allocation ไม่ใช่ normalized distribution
- เป็น data issue

คำถามถึงกรรมการ: **ควร normalize `employee_headcount_share_pct` ก่อนใช้ หรือ treat เป็น raw approximate share ที่มี missing corporate/other allocation?**

### `DIM_PRODUCT.dept_code` ว่างเกือบทั้งหมด

`DIM_PRODUCT.dept_code` เป็น null 109/110 rows มีแค่ `SF-Galaxy-Pro-2568` ที่มี `dept_code = SF`

Product universe ยังต่างจาก brand wording ใน slide deck:

- `DIM_PRODUCT.brand_family`: `FahMai`, `NovaTech`, `SaiFah`, `ArcWave`, `WatchKit`, `Dawn`
- Slides mention house brands เช่น SaiFah, DaoNuea, KluenSiang, WongKhoJon, JudChuem

คำถามถึงกรรมการ: **สำหรับ product/category/brand questions ควรถือว่า `DIM_PRODUCT` authoritative แม้ brand naming ต่างจาก slides/docs ไหม?**

### `FACT_SALES.retry_idempotency_marker` ว่าง

README พูดถึง retry markers ใน real-world data-quality artifacts แต่ `FACT_SALES.retry_idempotency_marker` เป็น null ทั้ง 117,105/117,105 rows

คำถามถึงกรรมการ: **Retry markers อยู่ใน logs หรือ narrative docs แทน `FACT_SALES.retry_idempotency_marker` หรือ column นี้ intentionally empty?**

### จำนวนใน `DIM_VENDOR` ต่างจาก slide-level universe

`DIM_VENDOR.csv` มี 6 rows และมี 2 rows ที่ `is_partner_brand = True` ในขณะที่ slide deck เคยระบุ `13+ vendors & 4 partner brands`

คำถามถึงกรรมการ: **ถ้าคำถามถาม vendor/partner-brand counts ควรตอบจาก `DIM_VENDOR` เท่านั้น หรือรวม broader narrative/render/log sources ด้วย?**

## คำถามถึงกรรมการ

คำถามแบบ copy/paste:

1. `FACT_BANK_TRANSACTION.related_entity_table` มี `FACT_SALES_DEPOSIT_BATCH` แต่ไม่มี CSV ชื่อนี้ เป็น virtual derived entity ใช่ไหม และทีมควร reconstruct หรือ resolve อย่างไร?
2. สำหรับ fact tables, `effective_date` มักว่าง 100% และ `as_of_date` เป็น `2026-01-15` ทั้งหมด Temporal joins ควรใช้ `business_event_date`, `posting_date`, หรือ column อื่น?
3. Versioned rows ใน `DIM_POLICY_VERSION` และ `DIM_VENDOR_CONTRACT_VERSION` เป็น half-open (`effective_date <= date < end_date`) หรือ inclusive of `end_date`?
4. สำหรับ `FACT_VENDOR_PAYMENT` ควร resolve contract validity ด้วย `business_event_date`, `posting_date`, `request_date`, หรือ explicit `vendor_contract_version_id`?
5. Duplicate PayWise invoice rows และ phantom promo redemptions เป็น intentional artifacts ที่ควร dedupe เฉพาะเมื่อคำถามระบุใช่ไหม?
6. `FACT_INVENTORY_MOVEMENT.related_txn_id` เป็น polymorphic โดย `XFER-*` เป็น transfer ids ไม่ใช่ missing `FACT_SALES.txn_id` references ใช่ไหม?
7. ID-like columns ทั้งหมด รวมถึง large numeric IDs เช่น `line_item_id` ควรถูก treat เป็น opaque strings เพื่อเลี่ยง precision/format issues ใช่ไหม?
8. ควร trust `DIM_DATE` holiday columns ไหม แม้ทุก holiday fields จะว่าง?
9. Branch/share columns เช่น `employee_headcount_share_pct` ควร normalize ก่อนใช้ หรือ treat เป็น raw approximate allocation?
10. สำหรับ product/vendor count questions ควรถือ tables authoritative เหนือ slide/narrative universe counts ใช่ไหม?
11. ถ้า `FACT_SALES.retry_idempotency_marker` ว่าง ควรหา retry/idempotency markers จากที่ไหน?
12. ถ้า dynamic reference ชี้ไป table-like name ที่ไม่มี physical file ควรตอบว่า "not available" หรือ derive จาก tables/logs อื่น?

## สมมติฐานการทำงานระหว่างรอคำตอบ

- อ่าน ID-like columns ทั้งหมดเป็น strings หรือ string-safe integer identifiers ไม่ใช่ floats
- Treat `related_entity_table` เป็น polymorphic; อย่า assume ว่าทุกค่าต้อง map ไป physical CSV
- ใช้ half-open date ranges สำหรับ versioned rows: `effective_date <= date < end_date`
- สำหรับ fact rows ใช้ `business_event_date` กับ business/event questions และ `posting_date` กับ accounting/posting questions แต่ต้อง record assumption นี้ไว้ใน answers/tools
- Treat known duplicate/phantom rows เป็น intentional data-quality artifacts; dedupe เฉพาะเมื่อ prompt ถาม dedupe/canonical/net result
- สร้าง lightweight table profiler ก่อน private questions: row counts, primary keys, FK coverage, date windows, null-heavy columns, และ dynamic reference values
- แยก table findings ออกจาก OCR/render provenance issues; ไฟล์นี้โฟกัสเฉพาะ `tables`

## หลักฐานที่ตรวจแล้ว

Main paths inspected:

- `super-ai-engineer-season-6-fah-mai-the-finale/tables`
- `super-ai-engineer-season-6-fah-mai-the-finale/README.md`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_BANK_TRANSACTION.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_VENDOR_PAYMENT.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_VENDOR_CONTRACT_VERSION.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_POLICY_VERSION.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_RETURN.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_SALES_LINE_ITEM.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_PROMO_REDEMPTION.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_INVENTORY_MOVEMENT.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_DATE.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_BRANCH.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_PRODUCT.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_VENDOR.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_SALES.csv`

Validation notes:

- พบ CSV 31 ไฟล์
- primary key column ในทุก CSV unique และ non-null
- พบ lowercase `dim_*` files 4 ไฟล์
- `FACT_SALES_DEPOSIT_BATCH` ปรากฏใน `FACT_BANK_TRANSACTION.related_entity_table` 28,279 rows
- พบ duplicate PayWise invoice groups 1 กลุ่ม
- พบ duplicate promo `txn_id` groups 4 กลุ่ม
- พบ `V-018` vendor payment contract-date mismatch 8 rows
- `DIM_DATE` holiday fields ว่าง

เอกสารนี้เป็น working audit note สำหรับเตรียมแข่งขัน ไม่ใช่ official rulebook
