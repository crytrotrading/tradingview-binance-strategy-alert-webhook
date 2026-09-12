"""Multi-market RSI/Fibonacci zone and retest dashboard."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from threading import Lock
import tempfile
import time

from flask import Flask, jsonify, render_template
import requests

from signal_engine import Candle, RetestStore, calculate_setup

app = Flask(__name__)

BINANCE_API_URL = os.getenv(
    "BINANCE_API_URL", "https://data-api.binance.vision"
).rstrip("/")
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "1000"))
CACHE_SECONDS = int(os.getenv("SIGNAL_CACHE_SECONDS", "30"))
STATE_DB = os.getenv(
    "STATE_DB", os.path.join(tempfile.gettempdir(), "fibo-retest-state.db")
)


def _parse_symbols(raw):
    symbols = []
    for item in raw.split(","):
        parts = item.strip().split(":", 1)
        if not parts[0]:
            continue
        display = parts[0].upper()
        exchange = (parts[1] if len(parts) == 2 else parts[0]).upper()
        symbols.append({"display": display, "exchange": exchange})
    return symbols


SYMBOLS = _parse_symbols(
    os.getenv("SYMBOLS", "BTC:BTCUSDT,ETH:ETHUSDT,SOL:SOLUSDT,XAU:XAUTUSDT")
)

http = requests.Session()
http.headers.update({"User-Agent": "FiboRetestDashboard/1.0"})
store = RetestStore(STATE_DB)
cache_lock = Lock()
analysis_cache = {}


def _get_json(path, params):
    response = http.get(f"{BINANCE_API_URL}{path}", params=params, timeout=12)
    response.raise_for_status()
    return response.json()


def _current_prices():
    payload = _get_json("/api/v3/ticker/price", {})
    wanted = {symbol["exchange"] for symbol in SYMBOLS}
    return {
        item["symbol"]: float(item["price"])
        for item in payload
        if item.get("symbol") in wanted
    }


def _closed_candles(symbol, timeframe):
    payload = _get_json(
        "/api/v3/klines",
        {"symbol": symbol, "interval": timeframe, "limit": KLINE_LIMIT},
    )
    now_ms = int(time.time() * 1000)
    return [
        Candle(
            open_time=int(item[0]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
        )
        for item in payload
        if int(item[6]) < now_ms
    ]


def _setup_for(symbol, timeframe):
    key = (symbol, timeframe)
    now = time.monotonic()
    with cache_lock:
        cached = analysis_cache.get(key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    setup = calculate_setup(_closed_candles(symbol, timeframe))
    with cache_lock:
        analysis_cache[key] = (now, setup)
    return setup


def _cell(symbol, timeframe, price):
    try:
        setup = _setup_for(symbol, timeframe)
        if setup is None:
            return {"status": "—", "price": price, "error": None, "no_signal": True}
        return store.evaluate(symbol, timeframe, setup, price)
    except Exception as exc:
        app.logger.warning("Failed %s %s: %s", symbol, timeframe, exc)
        return {"status": "!", "price": price, "error": str(exc)}


@app.get("/")
def dashboard():
    return render_template(
        "index.html",
        symbols=SYMBOLS,
        timeframes=TIMEFRAMES,
        refresh_seconds=max(5, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "10"))),
    )


@app.get("/api/dashboard")
def dashboard_data():
    try:
        prices = _current_prices()
    except Exception as exc:
        return jsonify({"error": f"โหลดราคาจาก Binance ไม่สำเร็จ: {exc}"}), 502

    rows = {
        symbol["exchange"]: {
            "symbol": symbol["exchange"],
            "display": symbol["display"],
            "price": prices.get(symbol["exchange"]),
            "timeframes": {},
        }
        for symbol in SYMBOLS
    }
    jobs = {}
    with ThreadPoolExecutor(max_workers=min(12, len(SYMBOLS) * len(TIMEFRAMES))) as pool:
        for symbol in SYMBOLS:
            price = prices.get(symbol["exchange"])
            if price is None:
                for timeframe in TIMEFRAMES:
                    rows[symbol["exchange"]]["timeframes"][timeframe] = {
                        "status": "!",
                        "error": "ไม่พบราคาคู่นี้",
                    }
                continue
            for timeframe in TIMEFRAMES:
                future = pool.submit(_cell, symbol["exchange"], timeframe, price)
                jobs[future] = (symbol["exchange"], timeframe)
        for future in as_completed(jobs):
            symbol, timeframe = jobs[future]
            rows[symbol]["timeframes"][timeframe] = future.result()

    return jsonify(
        {
            "updated_at": int(time.time() * 1000),
            "timeframes": TIMEFRAMES,
            "rows": list(rows.values()),
        }
    )


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)