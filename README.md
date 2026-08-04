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
- SQLite เป็นค่าเริ่มต้น รันง่ายบน Windows/Linux
- Docker พร้อมใช้งาน

## เริ่มใช้งาน

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

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

## Docker

```bash
docker compose up -d --build
```

ข้อมูล SQLite จะถูกเก็บใน volume `cpadd-data`

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

## หลักการของ Cherry CFO

1. แยกเงินส่วนตัวและบริษัท
2. ใช้ตัวเลขจากฐานข้อมูลเท่านั้น
3. บอกความไม่แน่นอนตรง ๆ
4. รักษา Cash Flow ก่อนเพิ่มภาระใหม่
5. รายการผ่อน 0% ก็ยังเป็นหนี้ ไม่ใช่เวทมนตร์ของฝ่ายการตลาด

## หมายเหตุด้านความปลอดภัย

MVP นี้ออกแบบสำหรับใช้งานส่วนตัวบนเครื่องหรือเครือข่ายที่เชื่อถือได้ API Key สามารถตั้งจาก environment variable เพื่อไม่ต้องบันทึกใน SQLite ก่อนเปิดใช้งานผ่านอินเทอร์เน็ตควรเพิ่ม Authentication, HTTPS, secret encryption และ backup policy
