# FahMai The Finale: จุดขัดแย้งในสไลด์และคำถามถึงกรรมการ

## สรุปสำหรับตัดสินใจ

เอกสารนี้รวบรวมจุดที่น่าสงสัยจาก `FahMai The Finale.pdf` เทียบกับไฟล์จริงใน workspace และ README ที่มากับ bundle จุดที่ควรถามกรรมการก่อนวางกลยุทธ์มี 5 เรื่องหลัก:

- **จำนวน tracks**: สไลด์บางหน้าพูดถึง 3 tracks/API track แต่หน้าสรุป tracks หลักบอกว่ามี 2 agentic tracks และห้ามใช้ remote API
- **ขอบเขต/รูปแบบ OCR**: สไลด์บอก OCR เป็นตัวอย่าง bank statement และส่ง JSONL แต่ sample submission ใน workspace เป็น CSV และมี artifact หลายชนิด
- **ไฟล์ provenance JSON**: OCR bundle มี sidecar/provenance JSON ที่ map กลับ `source_row_ids`; README ระบุเองว่าเป็น `grader_only`
- **กติกาแหล่งข้อมูลที่เชื่อถือได้**: README ระบุว่า database table เป็นแหล่งหลัก เว้นแต่ memo/policy version ที่ใหม่กว่า supersede แต่ product/docs/table universe บางส่วนไม่ตรงกัน
- **schema ของ endpoint/token**: back-test endpoint, response fields ที่จำเป็น และวิธีนับ token/cost ยังไม่ชัดพอสำหรับ implementation ที่ทำซ้ำได้

ข้อแนะนำชั่วคราว: อย่าใช้ provenance JSON เป็นแกนของ solution จนกว่าจะได้คำตอบจากกรรมการ, นับไฟล์จริงเอง, ทำ OCR adapter ให้รองรับทั้ง CSV sample และ JSONL/back-test, และเก็บ telemetry token/cost ให้ละเอียดตั้งแต่ต้น

## ประเด็นสำคัญที่ควรถามก่อน

### 1. จำนวน tracks: 3 tracks หรือ 2 tracks

สไลด์มีข้อความที่ไม่สอดคล้องกัน:

- หน้า 1: `Stage 1 - Kaggle 3 Tracks Multimodal Thai / EN Agentic`
- หน้า 17: scoring ระบุว่าใช้ formula เดียวกัน across `all 3 tracks` และกล่าวถึง `API`, `Local`, `ThaiLLM`
- หน้า 18: หัวข้อ `Two Tracks` และระบุแค่ `ThaiLLM-based` กับ `Open-Weight Local`
- หน้า 18 ยังระบุว่า agentic inference ต้องรันบน NTi compute และห้าม remote API fallback

ผลกระทบ: ถ้า API track ไม่มีจริง ห้ามออกแบบ workflow ที่พึ่ง remote API สำหรับ final/back-test แต่ถ้า API track ยังมีอยู่ scoring/cost baseline จะต่างกันมาก

คำถามที่ควรถาม: **สรุป official tracks คืออะไรแน่: API ยังมีไหม หรือมีแค่ Local, ThaiLLM, และ OCR แยกต่างหาก?**

### 2. ขอบเขต OCR: เฉพาะ bank statement หรือหลาย artifact types

สไลด์หน้า 19 ระบุว่า OCR sub-track คือ `Pull structured fields out of bank-statement renders` และ scope คือ `Bank-statement sample`

แต่ `super-ai-engineer-season-6-fah-mai-the-finale-ocr/sample__submission.csv` มี 3,750 rows และ artifact หลายประเภท เช่น:

- `WC-*`: warranty forms
- `VI-*`: vendor invoices
- `RC-*`: receipts
- `BS-*`: bank statements
- `MEMO-*`, `POL-*`, `EMAIL-*`, `TRAIN-*`, `VC-*`, `BN-*`, `AUD-*`, `T3-*`

ผลกระทบ: OCR model/schema สำหรับ bank statement อย่างเดียวอาจไม่พอ ถ้า leaderboard จริงรวมหลาย artifact type

คำถามที่ควรถาม: **OCR leaderboard ต้องทำเฉพาะ bank statements หรือทุก artifact ที่อยู่ใน sample submission?**

### 3. รูปแบบ submission ของ OCR: JSONL หรือ CSV

สไลด์หน้า 19 ระบุว่า `Submit a JSONL of extracted fields per image`

แต่ sample file เป็น CSV:

```text
artifact_id,pred_json
```

โดย `pred_json` เป็น JSON string ใน cell ของ CSV

ผลกระทบ: ถ้าส่งผิด format อาจ fail submission แม้ extraction ถูก

คำถามที่ควรถาม: **OCR submission official format คือ CSV แบบ sample หรือ JSONL ตามสไลด์? ถ้าทั้งสองแบบใช้คนละ phase ให้ระบุ phase ให้ชัด**

### 4. Provenance JSON ดูเหมือนเป็นข้อมูลสำหรับ grader เท่านั้น

OCR bundle มีไฟล์:

- `fahmai_renders_with_json/render_provenance.jsonl`
- `fahmai_renders_with_json/per_artifact/<type>/<artifact_id>.json`

ไฟล์เหล่านี้มี `source_fact_table`, `source_row_ids`, และ `visible_fields` ซึ่งสามารถ join กลับไปหา source rows ใน FACT/DIM tables ได้

README ของ OCR bundle ระบุว่า `release_lane` เป็น `grader_only` และอธิบายว่า provenance record เป็น grader-only เพราะ `source_row_ids` mapping จะทำให้ model solve visual-grounding question ได้ง่ายเกินไปโดย join กลับ table

ผลกระทบ: การใช้ sidecar/provenance JSON ใน solution อาจถูกมองว่า data leak หรือ cheating แม้ไฟล์อยู่ใน workspace

คำถามที่ควรถาม: **อนุญาตให้ใช้ `render_provenance.jsonl` และ `per_artifact/*.json` ในการแข่งขันไหม หรือถือเป็น grader-only/hint ที่ห้ามใช้?**

### 5. Schema ของ back-test endpoint ยังกำกวม

สไลด์หน้า 20 ระบุ agentic back-test:

```json
INPUT
{ "question": "..." }

OUTPUT
{ "id": "...",
  "total_output_token": N }
```

แต่ `answer` ปรากฏแยกบรรทัดใน extracted PDF text และไม่ชัดว่า output JSON ที่แท้จริงต้องมี field อะไรบ้าง

ผลกระทบ: backend endpoint อาจ fail contract หาก response shape ไม่ตรง spec และ token counting อาจกระทบ scoring

คำถามที่ควรถาม: **response schema จริงคือ `{id, answer, total_output_token}` ใช่ไหม? Input มี question id ไหม? Token count ต้องนับอย่างไรและใช้ tokenizer อะไร?**

## ข้อมูลหรือ manifest ที่ไม่ตรงกัน

### 1. จำนวนไฟล์ใน `docs/l1_kb` ไม่ตรงกับ README

`super-ai-engineer-season-6-fah-mai-the-finale/README.md` ระบุว่า:

```text
docs/l1_kb/ | 0 | L1 KB documents
```

แต่การนับไฟล์จริงพบ `docs/l1_kb` มี 118 files:

- 5 policy files
- 110 product markdown files
- store info/general FAQ files

ผลกระทบ: README count บางส่วนอาจ stale ต้องนับไฟล์จริงก่อน indexing

### 2. จำนวนลูกค้าไม่ตรงกัน

สไลด์หน้า 3 ระบุ `100K+ customers`

แต่ `DIM_CUSTOMER.csv` มี 30,000 rows

ผลกระทบ: ตัวเลขบนสไลด์อาจเป็น universe/narrative ไม่ใช่ public bundle truth

### 3. จำนวน vendor/partner brand ไม่ตรงกัน

สไลด์หน้า 3 ระบุ `13+ vendors & 4 partner brands`

แต่ `DIM_VENDOR.csv` มี 6 vendors:

- `V-001`
- `V-002`
- `V-006`
- `V-013`
- `V-014`
- `V-018`

และ rows ที่ `is_partner_brand = True` มี 2 rows

ผลกระทบ: ถ้าคำถามถามจำนวน vendors/partner brands ต้องรู้ว่าจะยึด table หรือ narrative slide

### 4. Product universe และชื่อ brand ไม่สอดคล้องกัน

สไลด์หน้า 3 ระบุ five house brands:

- SaiFah Phones / Tablets
- DaoNuea Laptops / Computers
- KluenSiang Audio
- WongKhoJon Wearables
- JudChuem Accessories

แต่ `DIM_PRODUCT.csv` มี 110 rows และ `brand_family` เป็น:

- FahMai
- NovaTech
- SaiFah
- ArcWave
- WatchKit
- Dawn

ในขณะที่ `docs/l1_kb/products` มี 110 product docs แต่ SKU overlap กับ `DIM_PRODUCT.csv` เพียงบางส่วนจากที่ตรวจเบื้องต้น

ผลกระทบ: product docs กับ product dimension อาจเป็นคนละ naming layer หรือมี stale mapping ต้องกำหนด authority rule

คำถามที่ควรถาม: **เมื่อ product docs, DIM_PRODUCT, และ slide brand universe ไม่ตรงกัน ให้ใช้ source ไหนเป็น authoritative สำหรับคำตอบ?**

### 5. นิยาม POS rows ไม่ชัด

สไลด์หน้า 3 ระบุ `500K+ POS rows`

จากการตรวจเบื้องต้น:

- `FACT_SALES.csv`: 117,105 rows
- `FACT_SALES_LINE_ITEM.csv`: 309,129 rows
- รวมสอง table นี้ประมาณ 426,234 rows
- POS TSV logs มี 7,196 files และประมาณ 160,321 data rows

ผลกระทบ: ตัวเลข `500K+ POS rows` อาจหมายถึง aggregate หลายแหล่ง หรือเป็น narrative count ที่ไม่ตรงกับ public files แบบตรงๆ

คำถามที่ควรถาม: **นิยาม `POS rows` ในสไลด์คือ rows จาก table ไหน/log ไหน และต้องนับซ้ำกับ FACT tables หรือไม่?**

## ข้อกังวลเกี่ยวกับ OCR bundle

### Provenance map visual artifacts กลับไปยัง source rows ได้

OCR sidecar JSON มีข้อมูลที่มีประโยชน์มากเกินกว่าการ OCR ปกติ เช่น:

- `artifact_id`
- `output_path`
- `source_fact_table`
- `source_row_ids`
- `visible_fields`
- `all_source_row_ids`

ตัวอย่างเช่น `per_artifact/vendor_invoice/VI-V-001-INV-2567-14617.json` ชี้ว่า artifact นี้มาจาก `FACT_VENDOR_PAYMENT` และ row id ใด

ถ้าใช้ข้อมูลนี้ ผู้เข้าแข่งขันอาจไม่ต้องอ่านภาพจริง แค่ join row id กลับไป source table ก็ได้คำตอบ ซึ่งขัดกับเจตนาของ OCR/visual grounding

### README ระบุว่า provenance เป็น grader-only

OCR README ระบุว่า provenance record เป็น `grader_only` แม้ PNG อยู่ใน public lane และอธิบายว่า mapping นี้ทำให้ model solve visual-grounding question ได้ง่ายเกินไป

สรุปความเสี่ยง: **อย่าใช้ provenance JSON ใน final solution จนกว่าจะมีคำตอบชัดจากกรรมการ**

### Metadata อาจไม่น่าเชื่อถือทั้งหมด

จากตัวอย่าง bank statement `BS-KBANK-OPER-2567-01`:

- มี transaction pages หลายหน้า เช่น `transactions_p1`, `transactions_p2`, `transactions_p10`, `transactions_p22`
- แต่ metadata ใน provenance/per-artifact ใส่ `source_row_ids` ชุดเดียวกันซ้ำหลาย transaction pages

ดังนั้นแม้กรรมการอนุญาตให้ใช้ provenance ก็ยังต้อง verify ความถูกต้อง ไม่ควร trust blindly

## คำถามถึงกรรมการ

ใช้ชุดคำถามนี้ถามกรรมการได้เลย เรียงจาก priority สูงสุด:

1. สรุป official tracks คืออะไรแน่: API track ยังมีไหม หรือ final มีแค่ Local, ThaiLLM, และ OCR แยกต่างหาก?
2. OCR submission official format คือ CSV แบบ `sample__submission.csv` หรือ JSONL ตามสไลด์? ถ้าใช้คนละ format ใน Kaggle/back-test ช่วยระบุ phase ให้ชัด
3. OCR scope จริงคือ bank statements เท่านั้น หรือทุก artifact type ที่ปรากฏใน sample submission?
4. อนุญาตให้ใช้ `render_provenance.jsonl` และ `per_artifact/*.json` ไหม หรือถือเป็น grader-only/hint ที่ห้ามใช้ในการแข่งขัน?
5. ถ้า structured tables, narrative docs, render artifacts, memo, และ policy version ขัดกัน ให้ใช้ authority rule อย่างไร?
6. โดยเฉพาะ product data: ถ้า `DIM_PRODUCT.csv`, `docs/l1_kb/products`, และ slide brand universe ไม่ตรงกัน ให้ยึด source ไหน?
7. Back-test agent endpoint input/output schema จริงคืออะไร? ต้อง return `{id, answer, total_output_token}` ใช่ไหม?
8. Token/cost scoring สำหรับ Local/ThaiLLM นับเฉพาะ output tokens หรือรวม input/context/tool traces ด้วย? ใช้ tokenizer อะไร?
9. Local grader สำหรับ public agentic questions (`grade.py`, `train_labels.json`) จะปล่อยที่ไหน? ใน Kaggle หรือ bundle แยก?
10. `No re-submission after deadline` หมายถึง Kaggle private, back-test window, หรือ final endpoint submission?
11. ตัวเลข universe บนสไลด์ เช่น `100K+ customers`, `13+ vendors`, `500K+ POS rows` เป็น narrative หรือเป็น expected count ที่ควร match public bundle?
12. Audit trail ที่ต้องส่งเป็น `{id}.txt` ต้องมีอะไรบ้าง และห้ามมี chain-of-thought หรือให้ส่งเฉพาะ tool/action logs?

## สมมติฐานการทำงานระหว่างรอคำตอบ

- อย่าใช้ OCR provenance/sidecar JSON เป็น part ของ final solution จนกว่ากรรมการจะอนุญาตชัดเจน
- Index และนับไฟล์จริงจาก filesystem เอง อย่าเชื่อ README หรือ slide counts เพียงอย่างเดียว
- ทำ OCR pipeline ให้รองรับทั้ง:
  - CSV sample format: `artifact_id,pred_json`
  - JSON output/back-test format: structured JSON per image/PDF
- ทำ schema adapter แยกสำหรับ OCR artifact types เพราะ sample มีมากกว่า bank statements
- สำหรับ agentic pipeline ให้ยึด source authority จาก README ชั่วคราว: database table authoritative เว้นแต่ memo/policy version ที่ใหม่กว่า supersedes
- เก็บ token/cost telemetry ต่อ question ตั้งแต่ต้น แม้ token counting spec ยังไม่ชัด
- ทำ endpoint response ให้ deterministic และ include fields ที่น่าจะต้องใช้: `id`, `answer`, `total_output_token`
- ออกแบบ pipeline ให้รันซ้ำได้ใน command เดียว และไม่ต้องอ่าน corpus ซ้ำทุก question

## หลักฐานที่ตรวจแล้ว

ไฟล์/แหล่งหลักที่ใช้ตรวจ:

- `FahMai The Finale.pdf`
- `super-ai-engineer-season-6-fah-mai-the-finale/README.md`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_BANK_ACCOUNT.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_BRANCH.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_CUSTOMER.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_PRODUCT.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/DIM_VENDOR.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_SALES.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/FACT_SALES_LINE_ITEM.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale/docs/l1_kb/`
- `super-ai-engineer-season-6-fah-mai-the-finale/logs/`
- `super-ai-engineer-season-6-fah-mai-the-finale-ocr/sample__submission.csv`
- `super-ai-engineer-season-6-fah-mai-the-finale-ocr/fahmai_renders_with_json/fahmai_renders_with_json/README.md`
- `super-ai-engineer-season-6-fah-mai-the-finale-ocr/fahmai_renders_with_json/fahmai_renders_with_json/render_provenance.jsonl`
- `super-ai-engineer-season-6-fah-mai-the-finale-ocr/fahmai_renders_with_json/fahmai_renders_with_json/per_artifact/vendor_invoice/VI-V-001-INV-2567-14617.json`
- `super-ai-engineer-season-6-fah-mai-the-finale-ocr/fahmai_renders_with_json/fahmai_renders_with_json/per_artifact/bank_statement/BS-BBL-OPER-2567-11.json`

หมายเหตุ: เอกสารนี้เป็นบันทึก audit/discrepancy จากข้อมูลที่ตรวจใน workspace ปัจจุบัน ไม่ใช่ official rulebook ของการแข่งขัน
