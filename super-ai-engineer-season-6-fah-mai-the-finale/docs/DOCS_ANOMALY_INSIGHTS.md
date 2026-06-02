# Insight Anomaly จากเอกสาร

ไฟล์นี้สรุป narrative evidence ที่เกี่ยวกับ anomaly ใน `email`, `l1_kb`, `memo`, และ `minutes`.

## สรุปสั้น

โฟลเดอร์เหล่านี้ไม่มี `[[CLAIM:...]]` marker. สัญญาณของมันมาจากชื่อไฟล์, วันที่, wording, และ link ไปยัง chat/table evidence.

ความเสี่ยงที่สำคัญที่สุดคือ:

- `l1_kb` มีปัญหา product และ policy consistency.
- Return policy ขัดกันระหว่าง KB, policy table, และ memo.
- Event memo/minutes ให้ governance context แต่ส่วนใหญ่มักไม่ระบุ root cause ตรง ๆ.
- Monthly emails และ minutes มีประโยชน์เป็น baseline communication cadence ไม่ใช่ anomaly label.

## บทบาทของแต่ละโฟลเดอร์

| Folder | Count | Role |
|---|---:|---|
| `email` | 25 | Monthly staff broadcasts และ CEO event email 1 ไฟล์. |
| `l1_kb` | 118 | Customer-facing knowledge base ด้าน product, policy, และ store info. |
| `memo` | 16 | เอกสาร policy/directive รวมถึง event-coded memos. |
| `minutes` | 26 | Monthly ops minutes และ event-coded meeting minutes. |

## ประเด็นหลัก

### Email

`EMAIL-ALLSTAFF-YYYY-MM.md` มีครบทั้ง 24 เดือน ตั้งแต่ 2024-01 ถึง 2025-12. ใช้เป็น monthly communication baseline.

`email__CEO__2025-01-15__e0000.md` เป็น event email พิเศษ. ไฟล์นี้ support CEO/leadership-transition event และควร ingest เป็น `event_evidence` ไม่ใช่ monthly baseline.

### L1 KB

`l1_kb/products` มี product docs 110 ไฟล์ และ `DIM_PRODUCT.csv` ก็มี product rows 110 rows แต่ SKU overlap กันเพียง 4 ตัว:

```text
AW-MN-001
DN-LT-010
NT-LT-001
WK-SW-004
```

แปลว่า KB product catalog และ structured product dimension เป็นคนละ catalog กันเกือบทั้งหมด. ไม่ควร drop ฝั่งใดฝั่งหนึ่งทันที; ให้ mark unmatched KB docs เป็น `kb_only_product` และ unmatched table rows เป็น `dim_only_product`.

Policy KB files ลงวันที่ 2026-03-01 ซึ่งอยู่นอก fiscal window 2024-2025. ให้ treat เป็น post-window snapshots เว้นแต่คำถามถามถึงปี 2026 โดยตรง.

Return policy คือ conflict ที่เสี่ยงที่สุด:

| Source | Return window |
|---|---:|
| `return_policy.md` | 15 days |
| `DIM_POLICY_VERSION.csv` ก่อน 2025-03-01 | 14 days |
| `DIM_POLICY_VERSION.csv` ตั้งแต่ 2025-03-01 | 21 days |
| `MEMO-PM-REFUND-2025-03-15.md` | ระบุว่า 30 -> 90 days ตั้งแต่ 2025-04-12 |

คำตอบเรื่อง return/refund ต้องมี effective-date และ source-priority logic.

### Memo

Event memos map official directive context เข้ากับ chat event codes:

- `memo__E2__2024-08-22__e0000.md`
- `memo__E3__2025-04-15__e0000.md`
- `memo__E9__2025-09-10__e0000.md`
- `memo__DQ3-2025-04-05__2025-04-05__e0000.md`
- `memo__DQ3-2025-09-10__2025-09-10__e0000.md`
- `memo__DQ4__2025-07-15__e0000.md`
- `memo__CEO__2025-01-15__e0000.md`

Event memos ส่วนใหญ่ใช้ wording กว้าง. ใช้เป็น official context ไม่ใช่ source เดียวสำหรับ anomaly root cause.

`MEMO-PM-REFUND-2025-03-15.md` เป็น policy-conflict document สำคัญ และควร reconcile กับ `DIM_POLICY_VERSION.csv`.

### Minutes

`MIN-OPS-YYYY-MM.md` มีครบทั้ง 24 เดือน ตั้งแต่ 2024-01 ถึง 2025-12. ใช้เป็น baseline operational cadence.

`min__CEO__2025-01-15__e0000.md` และ `min__E9__2025-09-10__e0000.md` เป็น event minutes. ทั้งสองมี completeness issues เช่น missing participants หรือ pending action owners. ใช้เป็น governance context ไม่ใช่ factual record ที่สมบูรณ์.

## แผนที่ Event ข้ามเอกสาร

| Event | Evidence | Interpretation |
|---|---|---|
| `CEO` | email + memo + minutes | Governance/leadership-transition event ที่ confidence สูงในวันที่ 2025-01-15. |
| `E3` | memo + LINE OA + LINE Works | Stockout event: memo ให้ directive context; chats ให้ operational/customer evidence ที่แรงกว่า. |
| `E9` | memo + minutes + LINE OA | Recall/vendor advisory context รอบวันที่ 2025-09-10. |
| `DQ3` | memo + LINE Works | Duplicate invoice incidents; memo ให้ official context, LINE Works ให้ claim markers. |
| `DQ4` | memo + LINE Works | Promo redemption double-logging incident; memo ให้ reporting context, LINE Works ให้ claim markers. |

## วิธีใช้งาน

Metadata ที่แนะนำ:

```json
{
  "source_family": "memo",
  "file_type": "event_evidence",
  "event_code": "DQ4",
  "event_date": "2025-07-15",
  "effective_date": null,
  "authority_rank": "narrative_context",
  "completeness_flag": null
}
```

กฎการใช้:

- Tables เป็น default source of truth สำหรับ structured values.
- KB มีประโยชน์สำหรับ customer-facing explanation แต่ต้อง validate product IDs, policy values, และ dates ก่อน.
- Memos อาจ supersede หรือ explain tables ได้ แต่ conflict ควรถูก flag.
- Event minutes เป็น governance evidence; อย่า over-trust participants, owners, หรือตัวเลขที่ missing.

Checks ที่แนะนำ:

- Reconcile `return_policy.md`, `MEMO-PM-REFUND-2025-03-15.md`, และ `DIM_POLICY_VERSION.csv`.
- Reconcile `l1_kb/products` กับ `DIM_PRODUCT.csv`.
- Join event memos กับ chat evidence ด้วย `event_code` และ `event_date`.
- ใช้ monthly email/minutes เป็น normal cadence baseline.
