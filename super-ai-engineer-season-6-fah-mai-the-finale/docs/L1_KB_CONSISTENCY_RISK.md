# ความเสี่ยงด้าน Consistency ของ L1 KB

ไฟล์นี้อธิบายว่าทำไม `l1_kb` จึงเป็น narrative source ที่เสี่ยงที่สุดสำหรับ RAG และ analysis.

## สรุปสั้น

`l1_kb` ดูเหมือน knowledge base สำหรับ customer support ที่พร้อมใช้ตอบลูกค้า แต่ข้อมูลไม่ได้ align กับ structured tables หรือ memos อย่างสมบูรณ์.

ใช้ `l1_kb` เป็น explanation layer ไม่ใช่ source of truth แบบไม่มีเงื่อนไข.

ความเสี่ยงหลัก:

- product catalog mismatch
- return-policy conflict
- policy files ลงวันที่หลัง main fiscal window
- customer-facing text อาจ override structured evidence ที่ดีกว่า ถ้า retrieval ไม่ถูกควบคุม

## Product Catalog ที่ไม่ตรงกัน

`docs/l1_kb/products` มี product docs 110 ไฟล์. `DIM_PRODUCT.csv` มี product rows 110 rows. จำนวนดูเหมือนตรงกัน แต่ SKU overlap กันเพียง 4 ตัว:

```text
AW-MN-001
DN-LT-010
NT-LT-001
WK-SW-004
```

ดังนั้นมี:

- 106 KB product docs ที่ไม่มี SKU match กับ `DIM_PRODUCT.csv`
- 106 rows ใน `DIM_PRODUCT.csv` ที่ไม่มี KB product doc match

ตัวอย่าง SKU ที่มีใน KB เท่านั้น:

```text
DN-LT-004
DN-DT-001
JC-CS-006
SF-SP-002
```

ตัวอย่าง SKU ที่มีใน table เท่านั้น:

```text
SKU-MASS-007
SKU-MASS-008
SF-Galaxy-Pro-2568
```

การตีความที่เป็นไปได้: `l1_kb/products` เป็น support/catalog layer ส่วน `DIM_PRODUCT.csv` เป็น operational sales/product dimension. สองแหล่งนี้ overlap กันแต่ไม่ใช่ source เดียวกัน.

## Policy ที่ขัดกัน

ค่า return-window ขัดกันหลาย source:

| Source | Value |
|---|---:|
| `return_policy.md` | 15 days |
| `DIM_POLICY_VERSION.csv`, 2024-01-01 ถึง 2025-03-01 | 14 days |
| `DIM_POLICY_VERSION.csv`, ตั้งแต่ 2025-03-01 | 21 days |
| `MEMO-PM-REFUND-2025-03-15.md` | ระบุว่า 30 days เปลี่ยนเป็น 90 days ตั้งแต่ 2025-04-12 |

นี่เป็นความเสี่ยงสูง เพราะคำตอบเรื่อง return/refund เป็น user-facing และขึ้นกับวันที่.

คำตอบที่ถูกต้องไม่ควรมาจาก chunk retrieval อย่างเดียว แต่ต้องมี:

- question date
- effective date
- source authority
- conflict handling

## ความเสี่ยงด้าน Date Window

Policy KB ทั้ง 5 ไฟล์อัปเดตวันที่ 2026-03-01.

Main fiscal window คือ 2024-01-01 ถึง 2025-12-31.

ดังนั้น policy KB อาจเป็น post-window snapshot. การใช้มันตอบคำถามของปี 2024 หรือ 2025 อาจทำให้เกิด temporal leakage.

ตัวอย่าง: `return_policy.md` บอก 15 days แต่ policy table ของปี 2024-2025 บอก 14 หรือ 21 days ตามวันที่.

## ลำดับความน่าเชื่อถือของ Source ที่แนะนำ

ใช้ structured tables ก่อนสำหรับ:

- policy numeric values
- effective-date logic
- transaction facts
- การมีอยู่ของ SKU ใน sales/product dimension

ใช้ `l1_kb` สำหรับ:

- customer-friendly explanations
- product descriptions
- procedure wording
- FAQ-style response drafting

ใช้ memos เป็น:

- official context
- possible supersession evidence
- conflict flags ที่อาจต้องให้ human/rule review

## Metadata ที่ควรเพิ่ม

สำหรับ KB chunks:

```json
{
  "source_family": "l1_kb",
  "kb_type": "product | policy | store_info",
  "authority_rank": "narrative_support",
  "temporal_warning": "post_fiscal_window"
}
```

สำหรับ product docs:

```json
{
  "sku_id_from_filename": "JC-CS-006",
  "sku_match_status": "kb_only_product"
}
```

สำหรับ policies:

```json
{
  "effective_date": "2025-03-01",
  "updated_at": "2026-03-01",
  "applies_to_period": "needs_validation"
}
```

## กฎการ Retrieval

ถ้าผู้ใช้ถามว่าสินค้ามีอยู่ใน sales data หรือไม่ ให้ตรวจ `DIM_PRODUCT.csv` ก่อน.

ถ้าผู้ใช้ถาม specs หรือ support wording ของสินค้า ให้ใช้ `l1_kb/products` แต่ต้องรักษาความต่างระหว่าง KB catalog กับ operational product dimension.

ถ้าผู้ใช้ถามว่า return window กี่วัน ให้ใช้ `DIM_POLICY_VERSION.csv` ตามวันที่ของคำถามก่อน แล้วค่อยตรวจ memo conflicts.

ถ้าผู้ใช้ถามขั้นตอนคืนสินค้า ให้ใช้ `return_policy.md` สำหรับ procedure wording แต่ห้ามใช้ตัวเลข 15-day จนกว่าจะตรวจ policy table และ memo แล้ว.

ถ้าผู้ใช้ไม่ให้วันที่สำหรับคำถาม policy ให้ถามวันที่ หรือระบุว่าคำตอบขึ้นกับวันที่.

## QA Checks

ควรสร้าง:

- `kb_product_reconciliation`
- `policy_conflict_registry`

Test queries ที่ควรใช้:

- `return window วันที่ 2025-04-20 คือกี่วัน`
- `JC-CS-006 อยู่ใน sales product dimension ไหม`
- `SKU-MASS-007 มี KB product page ไหม`

ควร cite sources ทุกครั้งสำหรับ policy answers เพราะ source ขัดกัน.

## การตีความเชิงปฏิบัติ

`l1_kb` ไม่ได้ไร้ประโยชน์หรือผิดทั้งหมด. มันเสี่ยงเพราะ agent เชื่อมันเร็วเกินไปได้ง่าย.

สำหรับ EDA ให้ treat เป็น narrative layer ที่ต้อง reconcile กับ tables.

สำหรับ RAG ให้ lookup structured source ก่อน แล้วค่อยใช้ KB text เพื่อทำให้คำตอบสุดท้ายอ่านง่าย.
