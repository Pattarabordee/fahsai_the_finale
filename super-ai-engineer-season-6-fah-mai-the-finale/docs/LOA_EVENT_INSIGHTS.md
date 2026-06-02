# Insight หลักฐาน Event จาก LINE OA

ไฟล์นี้อธิบายหลักฐานจากแชตลูกค้า LINE OA ที่มีสัญญาณสูงใน `chat_line_oa`.

## สรุปสั้น

ไฟล์ `loa__*.jsonl` เป็น event evidence ไม่ใช่แชตลูกค้าทั่วไป มีทั้งหมด 276 ไฟล์ แบ่งเป็น 3 event code คือ `E2`, `E3`, และ `D20`.

สัญญาณ anomaly ที่ชัดที่สุดคือ `E3`: 149 จาก 150 ไฟล์มี `CLAIM.E3.STOCKOUT_DUE_TO_COMPONENT_SUPPLY_SHORTAGE`. ดังนั้นให้ตีความ `E3` เป็นหลักฐาน stockout ฝั่งลูกค้าที่ confirmed แล้ว.

`E2` และ `D20` ไม่มี claim marker ให้ใช้เป็น stock-availability context หรือ control evidence ไม่ใช่ confirmed anomaly.

## รูปแบบชื่อไฟล์

`loa__E3__2025-04-22__e0037.jsonl` หมายถึง:

```text
source family = chat_line_oa
file type     = event_evidence
event code    = E3
event date    = 2025-04-22
sequence      = e0037
```

ไฟล์ `CHAT-LO-*.jsonl` คือแชตลูกค้าปกติ ไม่มี event code และไม่มี evidence sequence ID.

## ความหมายของ Code

| Code | Files | Claim markers | Meaning |
|---|---:|---:|---|
| `E3` | 150 | 149 | Stockout ที่ confirmed แล้ว และเกิดจาก component supply shortage. |
| `E2` | 120 | 0 | Burst การถาม availability ของ `Powercell X3` ช่วงต้น ใช้เป็น warning/context ได้. |
| `D20` | 6 | 0 | ตัวอย่าง periodic/control stock-check ของ `Powercell X3`. |

ไฟล์ `E3` ที่ไม่มี claim marker มีเพียง `chat_line_oa/loa__E3__2025-04-22__e0040.jsonl`. ไฟล์นี้ยังอยู่ในกลุ่ม `E3` ตามชื่อไฟล์ แต่ไม่ควรนับเป็น claim-marker evidence โดยตรง.

## สัญญาณสินค้า

`Powercell X3` คือ product context หลัก แต่การ match keyword ตรง ๆ อย่างเดียวไม่พอ.

`D20` พูดถึง `Powercell X3` ตรง ๆ ทั้ง 6 ไฟล์. `E2` พูดถึงตรง ๆ 108 จาก 120 ไฟล์. `E3` พูดถึงตรง ๆ แค่ 30 จาก 150 ไฟล์ เพราะหลายแชตใช้คำว่า `รุ่นนี้` หรือ `สินค้ารุ่นนี้`; claim marker จึงเป็นสัญญาณที่แรงกว่า keyword.

เวลา analyse ให้ใช้ทั้ง:

- exact/fuzzy product matching
- event code และ claim marker context

## เส้นเวลา

`E2` กระจุกอยู่ช่วง 2024-08-22 ถึง 2024-08-24. ดูเหมือน early stock-availability burst แต่ยังไม่ใช่ confirmed anomaly.

`E3` อยู่ช่วง 2025-04-15 ถึง 2025-05-12. นี่คือ customer-visible stockout window หลัก.

`D20` กระจายตั้งแต่ 2024-01-01 ถึง 2025-12-31. ใช้เป็น baseline/control evidence.

## วิธีใช้งาน

ควร extract metadata แบบนี้:

```json
{
  "source_family": "chat_line_oa",
  "file_type": "event_evidence",
  "event_code": "E3",
  "event_date": "2025-04-22",
  "event_seq": "e0037",
  "claim_type": "CLAIM.E3.STOCKOUT_DUE_TO_COMPONENT_SUPPLY_SHORTAGE",
  "product_hint": "Powercell X3 or inferred from event context"
}
```

ใช้ `loa__E3__*` เป็น customer-facing anomaly evidence ที่ confidence สูง. Join กับ inventory และ supply-chain tables เพื่อตรวจว่าสต็อกและ component shortage สอดคล้องกับหลักฐานแชตหรือไม่.

ใช้ `E2` เป็น possible early warning ก่อน `E3`, และใช้ `D20` เป็น control group สำหรับบทสนทนา stock-check ปกติ.
