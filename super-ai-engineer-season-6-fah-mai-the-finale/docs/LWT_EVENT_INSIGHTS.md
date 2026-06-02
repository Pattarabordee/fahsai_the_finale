# Insight หลักฐาน Event จาก LINE Works

ไฟล์นี้อธิบายหลักฐานภายในจาก LINE Works ที่มีสัญญาณสูงใน `chat_line_works`.

## สรุปสั้น

`chat_line_works` มีไฟล์ JSONL ที่ valid 15,802 ไฟล์:

- 15,634 ไฟล์เป็น internal thread ปกติแบบ `THREAD-LW-*`
- 168 ไฟล์เป็น event evidence แบบ `lwt__*`
- เหลือไฟล์ `.md` จำนวน 0 ไฟล์

สัญญาณสำคัญกระจุกอยู่ใน `lwt__*`. ไฟล์ `THREAD-LW-*` ปกติมีประโยชน์เป็น background แต่ parsed threads ไม่พบ claim marker.

`lwt__*` มี claim marker รวม 81 รายการ ครอบคลุม finance, ops, approval, data quality, และ leadership events.

## รูปแบบชื่อไฟล์

Thread ปกติ:

```text
THREAD-LW-20250130-b4d001.jsonl
```

นี่คือ internal thread ปกติของวันที่ 2025-01-30. วันที่อ่านจาก `YYYYMMDD` ใน prefix.

หลักฐาน event ที่มี date field ชัดเจน:

```text
lwt__L1__2024-04-15__r0000.jsonl
```

หมายถึง event code `L1`, event date `2024-04-15`, reference sequence `r0000`.

หลักฐาน event ที่วันที่อยู่ใน code:

```text
lwt__DQ3-2025-04-05__e0000.jsonl
```

หมายถึง event code `DQ3-2025-04-05`; event date คือ `2025-04-05`; sequence คือ `e0000`.

ตอนนี้ไม่มีชื่อไฟล์ใน `chat_line_works` ที่เก็บวันที่เดียวกันไว้สองตำแหน่งแล้ว. Redundant trailing date ถูกลบเฉพาะกรณีที่วันที่เดียวกันมีอยู่ใน prefix หรือ event code แล้ว.

## ความหมายของ Code

| Code | Files | Claim markers | Meaning |
|---|---:|---:|---|
| `DQ3-2025-04-05` | 30 | 17 | Incident duplicate invoice ID รอบเมษายน. |
| `DQ3-2025-09-10` | 30 | 15 | Incident duplicate invoice ID รอบกันยายน. |
| `DQ4` | 40 | 16 | Promo redemption ถูก double-log จาก app bug. |
| `E3` | 4 | 4 | Internal confirmation ของ stockout จาก component shortage. |
| `E2` | 4 | 3 | หลักฐาน internal delivery delay จาก carrier disruption. |
| `L1` | 14 | 12 | Refund approved ภายใน agent authority. |
| `L2` | 12 | 6 | Payment signed ภายใต้ manager authority. |
| `L3` | 8 | 6 | Invoice processed ภายใต้ vendor contract. |
| `CEO` | 12 | 2 | หลักฐาน leadership transition handover. |
| `D20` | 6 | 0 | Daily/customer-ops control evidence. |
| `SIGN-L1` | 4 | 0 | Supporting signoff context สำหรับ `L1`. |
| `SIGN-L2` | 4 | 0 | Supporting signoff context สำหรับ `L2`. |

## เส้นเวลา

`CEO` กระจุกอยู่วันที่ 2025-01-15.

`DQ3` มี incident date แยกกัน 2 วัน: 2025-04-05 และ 2025-09-10. การเก็บวันที่ไว้ใน event code ช่วยแยกรอบ duplicate-invoice สองรอบนี้ออกจากกัน.

`DQ4` อยู่ช่วง 2025-07-15 ถึง 2025-07-31 ซึ่งตรงกับ window ของ promo redemption double-logging.

`E2` อยู่ช่วง 2024-08-22 ถึง 2024-08-24.

`E3` อยู่ช่วง 2025-04-15 ถึง 2025-05-12.

`L1`, `L2`, และ `L3` เป็น recurring governance evidence ไม่ใช่ incident burst แบบครั้งเดียว.

## ความสัมพันธ์กับ LINE OA

`loa__E3__*` เป็น customer-facing stockout evidence. `lwt__E3__*` เป็น internal ops confirmation ของ stockout event เดียวกันในภาพรวม. ควร join สอง source นี้ด้วย `E3` เพื่อเชื่อม customer impact กับ internal cause/status.

ต้องระวัง `E2`: ใน LINE Works หมายถึง delivery delay แต่ใน LINE OA เป็น stock-availability context. Code เดียวกันอาจมีความหมายต่างกันตาม source family.

## วิธีใช้งาน

ควร extract metadata:

```json
{
  "source_family": "chat_line_works",
  "file_type": "event_evidence",
  "event_code": "DQ4",
  "event_date": "2025-07-15",
  "event_seq": "e0001",
  "claim_type": "CLAIM.DQ4.PROMO_REDEMPTION_DOUBLE_LOGGED_BY_APP_BUG",
  "business_domain": "promotion_data_quality"
}
```

กฎการอ่านวันที่:

- `THREAD-LW-YYYYMMDD-*`: อ่านวันที่จาก compact prefix.
- `lwt__DQ3-YYYY-MM-DD__*`: อ่านวันที่จาก event code.
- `lwt__<code>__YYYY-MM-DD__*` แบบอื่น: อ่านวันที่จาก date field หลัง code.

Join ที่แนะนำ:

- `DQ3` -> vendor payment และ invoice tables
- `DQ4` -> promo redemption facts
- `E2` -> shipping facts
- `E3` -> inventory movement และ monthly inventory snapshots
- `L1` -> refunds และ returns
- `L2` -> vendor payments และ authority tables
- `L3` -> vendor contracts และ invoice data

ให้ treat `lwt__*` เป็น high-signal internal evidence. ให้ treat `THREAD-LW-*` เป็น background context เว้นแต่มีสัญญาณอื่นเชื่อมกับ event.
