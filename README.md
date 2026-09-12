# Fibo Retest Monitor

เว็บแดชบอร์ดติดตาม RSI/Fibonacci signals หลายคู่และหลาย Timeframe โดยไม่ต้องเปิด
TradingView แอปคำนวณสัญญาณจากแท่งปิด และตรวจราคาปัจจุบันกับโซน Fibo 0–23.6%

- เข้าโซนครั้งแรก: `BUY` หรือ `SELL`
- ออกจากโซน: `—`
- กลับเข้าโซนเดิม: `BUY RETEST` หรือ `SELL RETEST`
- เมื่อพบ setup ใหม่ สถานะ Retest ของคู่นั้นและ Timeframe นั้นจะเริ่มใหม่

## เริ่มใช้งาน

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

เปิด `http://localhost:5000`

ค่าเริ่มต้นแสดง BTC, ETH, SOL และ XAU (ใช้ตลาด `XAUTUSDT` ของ Binance)
บน Timeframe `1m, 5m, 15m, 1h, 4h, 1d`

## ตั้งค่า

กำหนดคู่ด้วย environment variable รูปแบบ `ชื่อแสดงผล:ชื่อบน Binance`:

```bash
SYMBOLS="BTC:BTCUSDT,ETH:ETHUSDT,XAU:XAUTUSDT" python app.py
```

ตัวเลือกอื่น:

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---:|---|
| `DASHBOARD_REFRESH_SECONDS` | 10 | ความถี่รีเฟรชหน้า |
| `SIGNAL_CACHE_SECONDS` | 30 | อายุ cache การคำนวณ |
| `KLINE_LIMIT` | 1000 | จำนวนแท่งย้อนหลังต่อคู่/TF |
| `STATE_DB` | `/tmp/fibo-retest-state.db` | ไฟล์เก็บสถานะ Retest |
| `BINANCE_API_URL` | `https://data-api.binance.vision` | Binance public market-data endpoint |

แอปนี้เป็นหน้าติดตามสัญญาณเท่านั้นและไม่ส่งคำสั่งซื้อขาย ข้อมูล XAUUSD จาก
โบรกเกอร์อื่นอาจต่างจาก XAUTUSDT ทั้งราคาและ volume
