# Fibo Retest Monitor

เว็บแดชบอร์ดติดตาม RSI/Fibonacci signals หลายคู่และหลาย Timeframe โดยไม่ต้องเปิด
TradingView แอปคำนวณสัญญาณจากแท่งปิด และตรวจราคาปัจจุบันกับโซน Fibo 0–23.6%

- เข้าโซนครั้งแรก: `BUY` หรือ `SELL`
- ออกจากโซน: `—`
- กลับเข้าโซนเดิม: `BUY RETEST` หรือ `SELL RETEST`
- เมื่อพบ setup ใหม่ สถานะ Retest ของคู่นั้นและ Timeframe นั้นจะเริ่มใหม่
- ค้นหาคู่ได้ทันที และค่าเริ่มต้นแสดงเฉพาะคู่ที่มีสัญญาณโดยเรียงไว้ด้านบน

หน้า `/smc` เป็น SMCxSTO V3.0 scanner ตาม preset `Trend 15m / Order Block
5m / Stochastic 1m` แสดง BUY/SELL พร้อม Entry, TP, SL, RR 1:2.5, Grade และ
เวลาสัญญาณ แยก Binance และ Windsor MT5

## เริ่มใช้งาน

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

บน Windows ให้เปิดและล็อกอิน Windsor MT5 ก่อน จากนั้นเปิด `http://localhost:5000`

เปิดข่าวและ Events จาก altFINS โดยตั้ง API Key ใน Command Prompt ก่อนรัน:

```bat
set ALTFINS_API_KEY=วางคีย์ของคุณที่นี่
py app.py
```

API Key จะอ่านจาก environment เท่านั้นและต้องไม่บันทึกลง Git แถบข่าวแสดง
รายการสำคัญก่อน แปลงเวลาเป็นเวลาไทย และแปลหัวข้อผ่าน MyMemory Translation API
โดยใช้ภาษาอังกฤษเดิมเป็นข้อมูลสำรอง

altFINS อัปเดตเพียง 2 รอบต่อวันเวลาไทย เวลา 07:00 และ 19:00 ข้อมูลถูกบันทึก
ลงไฟล์ใน `%LOCALAPPDATA%\FiboRetestMonitor` การรีเฟรชหน้าเว็บหรือปิด–เปิด
โปรแกรมจะใช้ข้อมูลเดิมโดยไม่เสียเครดิตเพิ่มจนถึงรอบถัดไป

หน้าซ้ายแสดง Top 200 คู่ USDT จาก Binance เรียงตามมูลค่าซื้อขาย 24 ชั่วโมง
หน้าขวาแสดงทุก Symbol ที่เปิดใน Market Watch ของ Windsor MT5 โดยอัตโนมัติ
รวม Forex, โลหะ และ CFD โปรแกรมตัด suffix ของโบรกเกอร์ เช่น `EURUSDc`
เพื่อแสดงเป็น `EURUSD` ทั้งสองฝั่งคำนวณ Timeframe
`1m, 5m, 15m, 1h, 4h, 1d`

ฝั่ง Windsor แสดงช่วงเวลาเทรดหลักและช่วงรองเป็นเวลาไทย (`Asia/Bangkok`)
ตามตารางใน `trading_sessions.py` คู่ที่ไม่มีข้อมูลช่วงเวลาจะแสดง `—`

## ตั้งค่า

กำหนดจำนวนอันดับและคู่ที่ต้องแสดงเพิ่มได้ เช่น:

```bash
TOP_MARKETS=50 FOREX_SYMBOLS="XAUUSD,EURUSD,GBPUSD,USDJPY" python app.py
```

ตัวเลือกอื่น:

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---:|---|
| `TOP_MARKETS` | 200 | จำนวนคู่ USDT อันดับสูงสุด (สูงสุด 200) |
| `PINNED_SYMBOLS` | ว่าง | คู่ Binance ที่แสดงเพิ่มนอกเหนือจากอันดับ |
| `FOREX_SYMBOLS` | 24 คู่หลัก | คู่ที่อ่านจาก Windsor MT5 |
| `MT5_USE_MARKET_WATCH` | true | อ่านทุกคู่ที่แสดงใน Market Watch |
| `MT5_SYMBOL_SUFFIX` | `c` | suffix ที่ตัดออกจากชื่อบนหน้าเว็บ |
| `MT5_PATH` | ตรวจอัตโนมัติ | path ของ `terminal64.exe` กรณีมี MT5 หลายตัว |
| `MT5_SERVER_UTC_OFFSET_HOURS` | `auto` | ชดเชยเวลาเซิร์ฟเวอร์ MT5; Windsor ปกติ +2/+3 ตาม DST |
| `ALTFINS_API_KEY` | ว่าง | API Key สำหรับ News และ Calendar Events |
| `ALTFINS_REFRESH_HOURS` | `7,19` | ชั่วโมงอัปเดตข่าวตามเวลาไทย |
| `ALTFINS_CACHE_FILE` | Local AppData | ไฟล์ cache ข่าวถาวร |
| `ENABLE_THAI_TRANSLATION` | true | แปลหัวข้อข่าวและ Events เป็นไทย |
| `DASHBOARD_REFRESH_SECONDS` | 30 | ความถี่รีเฟรชหน้า |
| `SIGNAL_CACHE_SECONDS` | 60 | อายุ cache การคำนวณ |
| `MARKET_CACHE_SECONDS` | 300 | อายุ cache การจัดอันดับ 24 ชั่วโมง |
| `KLINE_LIMIT` | 1000 | จำนวนแท่งย้อนหลังต่อคู่/TF |
| `STATE_DB` | โฟลเดอร์ชั่วคราวของระบบ | ไฟล์เก็บสถานะ Retest |
| `BINANCE_API_URL` | `https://data-api.binance.vision` | Binance public market-data endpoint |

แอปนี้เชื่อม MT5 แบบอ่านข้อมูลเท่านั้นและไม่ส่งคำสั่งซื้อขาย ต้องเปิด MT5 และ
Command Prompt ที่รันเว็บค้างไว้ ข้อมูล volume ของ Forex เป็น tick volume จาก Windsor
