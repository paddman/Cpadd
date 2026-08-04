# Cpadd — Cherry CFO

ระบบบริหารการเงินบ้านแบบ Local-first พร้อม AI Agent **Cherry CFO** โดยเริ่มต้นรองรับ **Qwen 3.5 9B** ผ่าน OpenAI-compatible API เช่น vLLM, SGLang, LM Studio หรือ Ollama gateway

## สิ่งที่มีใน MVP

- Dashboard กระแสเงินสดแบบ วัน / สัปดาห์ / เดือน / ปี
- บันทึกรายรับ รายจ่าย เงินออม ชำระหนี้ และรายการวางแผน
- แยกเงินส่วนตัว บริษัท และเงินสำรองจ่ายแทนบริษัท
- ทะเบียนหนี้ ดอกเบี้ย ค่างวด จำนวนงวด และยอดคงเหลือ
- Planned Purchase สำหรับของที่กำลังตัดสินใจ เช่น Smartwatch
- Cherry CFO Agent วิเคราะห์ข้อมูลจริงจากฐานข้อมูล ไม่เดาตัวเลขเอง
- หน้า Settings สำหรับ Qwen: Base URL, Model, API Key, Temperature, Max Tokens และ Timeout
- **Statement OCR อัตโนมัติ** สำหรับ PDF และรูปภาพภาษาไทย/อังกฤษ
- SQLite เป็นค่าเริ่มต้น รันง่ายบน Windows/Linux
- Docker พร้อมใช้งาน

## Statement OCR

เปิด `http://localhost:8080/ocr` หรือกด **Statement OCR** จากเมนูหลัก

ขั้นตอนทำงาน:

1. PDF ที่มี text layer จะดึงข้อความตรงก่อน ไม่เสียเวลาทำ OCR โดยไม่จำเป็น
2. PDF สแกนและไฟล์ PNG/JPG/WEBP/TIFF ใช้ Tesseract `tha+eng`
3. Qwen ที่ตั้งไว้จะจัดข้อความเป็น Statement metadata และรายการธุรกรรม
4. ผู้ใช้ตรวจและเลือกรายการก่อนนำเข้า Cash Flow
5. ระบบกันการอัปโหลดไฟล์เดิมซ้ำด้วย SHA-256 และกันนำเข้า Statement เดิมซ้ำ

รองรับการอ่าน:

- วันที่ใช้บัตรและวันที่บันทึก
- Description / Merchant
- ยอด Debit, Credit และ Payment
- Previous Balance, Amount Due และ Total Balance
- รายการผ่อนแบบ `03/10`, `05/10`
- แยก Payment เป็น `transfer` เพื่อไม่ให้ Cash Flow นับรายจ่ายซ้ำกับยอดรูด

ไฟล์ต้นฉบับจะไม่ถูกเก็บ แต่ข้อความ OCR และผลแยกรายการจะถูกเก็บใน SQLite หากเปิดใช้ Qwen ข้อความ OCR จะถูกส่งไปยัง endpoint ที่ตั้งไว้ จึงควรใช้ Local Qwen สำหรับเอกสารที่มีข้อมูลส่วนบุคคล

## เริ่มใช้งาน

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

การรันแบบไม่ใช้ Docker ต้องติดตั้ง Tesseract และภาษาไทย/อังกฤษในระบบปฏิบัติการก่อน

เปิด `http://localhost:8080`

## ตั้งค่า Qwen 3.5 9B

ตัวอย่าง vLLM endpoint:

```env
QWEN_BASE_URL=http://127.0.0.1:8000/v1
QWEN_MODEL=qwen3.5-9b
QWEN_API_KEY=local
```

ชื่อโมเดลต้องตรงกับชื่อที่ runtime เสิร์ฟจริง เช่นค่าจาก `--served-model-name`

ทดสอบ API โดยตรง:

```bash
curl http://127.0.0.1:8000/v1/models
```

จากนั้นเข้าเมนู **Qwen Settings** ใน Cpadd แล้วกด **ทดสอบการเชื่อมต่อ**

## ตั้งค่า OCR

```env
OCR_LANGUAGES=tha+eng
OCR_DPI=220
OCR_MAX_PAGES=30
OCR_MAX_UPLOAD_MB=20
OCR_USE_QWEN_DEFAULT=true
```

หมายเหตุ: `OCR_USE_QWEN_DEFAULT` เป็นค่าเริ่มต้นระดับระบบ ส่วนหน้าอัปโหลดสามารถเปิดหรือปิด Qwen แยกในแต่ละครั้งได้

## Docker

```bash
docker compose up -d --build
```

Docker image จะติดตั้ง Tesseract พร้อม `eng` และ `tha` ให้อัตโนมัติ ข้อมูล SQLite จะถูกเก็บใน volume `cpadd-data`

## API หลัก

- `GET /api/dashboard?period=month`
- `GET|POST /api/transactions`
- `DELETE /api/transactions/{id}`
- `GET|POST /api/debts`
- `PUT|DELETE /api/debts/{id}`
- `GET /api/settings/qwen`
- `PUT /api/settings/qwen`
- `POST /api/settings/qwen/test`
- `POST /api/agent/chat`
- `POST /api/statements/preview` — multipart upload เพื่อ OCR และ preview
- `GET /api/statements`
- `GET /api/statements/{id}`
- `POST /api/statements/{id}/import`

## หลักการของ Cherry CFO

1. แยกเงินส่วนตัวและบริษัท
2. ใช้ตัวเลขจากฐานข้อมูลเท่านั้น
3. บอกความไม่แน่นอนตรง ๆ
4. รักษา Cash Flow ก่อนเพิ่มภาระใหม่
5. รายการผ่อน 0% ก็ยังเป็นหนี้ ไม่ใช่เวทมนตร์ของฝ่ายการตลาด
6. OCR ต้องให้ผู้ใช้ตรวจทานก่อนบันทึก เพราะเลข 8 กับเลข 3 ยังทำให้คอมพิวเตอร์มีเรื่องกันได้

## หมายเหตุด้านความปลอดภัย

MVP นี้ออกแบบสำหรับใช้งานส่วนตัวบนเครื่องหรือเครือข่ายที่เชื่อถือได้ API Key สามารถตั้งจาก environment variable เพื่อไม่ต้องบันทึกใน SQLite ก่อนเปิดใช้งานผ่านอินเทอร์เน็ตควรเพิ่ม Authentication, HTTPS, secret encryption, database encryption และ backup policy
