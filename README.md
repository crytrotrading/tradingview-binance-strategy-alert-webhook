# Fibo Retest Monitor

เว็บแดชบอร์ดติดตาม RSI/Fibonacci signals หลายคู่และหลาย Timeframe โดยไม่ต้องเปิด
TradingView แอปคำนวณสัญญาณจากแท่งปิด และตรวจราคาปัจจุบันกับโซน Fibo 0–23.6%

- เข้าโซนครั้งแรก: `BUY` หรือ `SELL`
- ออกจากโซน: `—`
- กลับเข้าโซนเดิม: `BUY RETEST` หรือ `SELL RETEST`
- เมื่อพบ setup ใหม่ สถานะ Retest ของคู่นั้นและ Timeframe นั้นจะเริ่มใหม่
- ค้นหาคู่ได้ทันที และค่าเริ่มต้นแสดงเฉพาะคู่ที่มีสัญญาณโดยเรียงไว้ด้านบน

## เริ่มใช้งาน

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

บน Windows ให้เปิดและล็อกอิน Windsor MT5 ก่อน จากนั้นเปิด `http://localhost:5000`

หน้าซ้ายแสดง Top 100 คู่ USDT จาก Binance เรียงตามมูลค่าซื้อขาย 24 ชั่วโมง
หน้าขวาแสดงทุก Symbol ที่เปิดใน Market Watch ของ Windsor MT5 โดยอัตโนมัติ
รวม Forex, โลหะ และ CFD โปรแกรมตัด suffix ของโบรกเกอร์ เช่น `EURUSDc`
เพื่อแสดงเป็น `EURUSD` ทั้งสองฝั่งคำนวณ Timeframe
`1m, 5m, 15m, 1h, 4h, 1d`

## ตั้งค่า

กำหนดจำนวนอันดับและคู่ที่ต้องแสดงเพิ่มได้ เช่น:

```bash
TOP_MARKETS=50 FOREX_SYMBOLS="XAUUSD,EURUSD,GBPUSD,USDJPY" python app.py
```

ตัวเลือกอื่น:

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---:|---|
| `TOP_MARKETS` | 100 | จำนวนคู่ USDT อันดับสูงสุด (สูงสุด 100) |
| `PINNED_SYMBOLS` | ว่าง | คู่ Binance ที่แสดงเพิ่มนอกเหนือจากอันดับ |
| `FOREX_SYMBOLS` | 24 คู่หลัก | คู่ที่อ่านจาก Windsor MT5 |
| `MT5_USE_MARKET_WATCH` | true | อ่านทุกคู่ที่แสดงใน Market Watch |
| `MT5_SYMBOL_SUFFIX` | `c` | suffix ที่ตัดออกจากชื่อบนหน้าเว็บ |
| `MT5_PATH` | ตรวจอัตโนมัติ | path ของ `terminal64.exe` กรณีมี MT5 หลายตัว |
| `DASHBOARD_REFRESH_SECONDS` | 30 | ความถี่รีเฟรชหน้า |
| `SIGNAL_CACHE_SECONDS` | 60 | อายุ cache การคำนวณ |
| `MARKET_CACHE_SECONDS` | 300 | อายุ cache การจัดอันดับ 24 ชั่วโมง |
| `KLINE_LIMIT` | 1000 | จำนวนแท่งย้อนหลังต่อคู่/TF |
| `STATE_DB` | โฟลเดอร์ชั่วคราวของระบบ | ไฟล์เก็บสถานะ Retest |
| `BINANCE_API_URL` | `https://data-api.binance.vision` | Binance public market-data endpoint |

แอปนี้เชื่อม MT5 แบบอ่านข้อมูลเท่านั้นและไม่ส่งคำสั่งซื้อขาย ต้องเปิด MT5 และ
Command Prompt ที่รันเว็บค้างไว้ ข้อมูล volume ของ Forex เป็น tick volume จาก Windsor
