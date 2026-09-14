"""Multi-market RSI/Fibonacci zone and retest dashboard."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from threading import Lock
import tempfile
import time

from flask import Flask, jsonify, render_template
import requests

from altfins_provider import AltFinsFeed
from mt5_provider import Mt5MarketData
from signal_engine import Candle, RetestStore, calculate_setup
from smc_engine import calculate_smc_signal
from trading_sessions import sessions_for_symbol

app = Flask(__name__)

BINANCE_API_URL = os.getenv(
    "BINANCE_API_URL", "https://data-api.binance.vision"
).rstrip("/")
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "1000"))
CACHE_SECONDS = int(os.getenv("SIGNAL_CACHE_SECONDS", "60"))
MARKET_CACHE_SECONDS = int(os.getenv("MARKET_CACHE_SECONDS", "300"))
TOP_MARKETS = min(200, max(1, int(os.getenv("TOP_MARKETS", "200"))))
FOREX_SYMBOLS = [
    item.strip().upper()
    for item in os.getenv(
        "FOREX_SYMBOLS",
        "XAUUSD,EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,NZDUSD,USDCAD,"
        "EURJPY,GBPJPY,EURGBP,EURAUD,EURCAD,EURCHF,GBPCHF,GBPAUD,"
        "GBPCAD,AUDJPY,NZDJPY,CADJPY,CHFJPY,AUDNZD,AUDCAD,NZDCAD",
    ).split(",")
    if item.strip()
]
MT5_USE_MARKET_WATCH = os.getenv("MT5_USE_MARKET_WATCH", "true").lower() not in {
    "0", "false", "no",
}
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


PINNED_SYMBOLS = _parse_symbols(os.getenv("PINNED_SYMBOLS", ""))
EXCLUDED_BASES = {
    "USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "USDS", "USD1",
    "BFUSD", "AEUR", "EUR", "TRY", "BRL", "GBP", "AUD", "BIDR", "IDRT",
    "UAH", "NGN", "RUB", "ZAR",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

http = requests.Session()
http.headers.update({"User-Agent": "FiboRetestDashboard/1.0"})
store = RetestStore(STATE_DB)
mt5_data = Mt5MarketData()
altfins_feed = AltFinsFeed()
cache_lock = Lock()
analysis_cache = {}
smc_cache = {}
market_cache = None


def _get_json(path, params):
    response = http.get(f"{BINANCE_API_URL}{path}", params=params, timeout=12)
    response.raise_for_status()
    return response.json()


def _rank_markets(payload, limit):
    candidates = []
    for item in payload:
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        if (
            base in EXCLUDED_BASES
            or base.endswith(LEVERAGED_SUFFIXES)
            or not base
        ):
            continue
        try:
            volume = float(item.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        candidates.append((volume, base, symbol))
    candidates.sort(reverse=True)
    return [
        {"display": base, "exchange": symbol}
        for _, base, symbol in candidates[:limit]
    ]


def _with_pinned_markets(ranked, pinned, limit):
    pinned_symbols = {item["exchange"] for item in pinned}
    return pinned + [
        item for item in ranked if item["exchange"] not in pinned_symbols
    ][:limit]


def _market_symbols():
    global market_cache
    now = time.monotonic()
    with cache_lock:
        if market_cache and now - market_cache[0] < MARKET_CACHE_SECONDS:
            return market_cache[1]
    ranked = _rank_markets(
        _get_json("/api/v3/ticker/24hr", {}),
        TOP_MARKETS + len(PINNED_SYMBOLS),
    )
    symbols = _with_pinned_markets(ranked, PINNED_SYMBOLS, TOP_MARKETS)
    with cache_lock:
        market_cache = (now, symbols)
    return symbols


def _current_prices(symbols):
    payload = _get_json("/api/v3/ticker/price", {})
    wanted = {symbol["exchange"] for symbol in symbols}
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
            open=float(item[1]),
        )
        for item in payload
        if int(item[6]) < now_ms
    ]


def _cached_setup(key, candle_loader):
    now = time.monotonic()
    with cache_lock:
        cached = analysis_cache.get(key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    setup = calculate_setup(candle_loader())
    with cache_lock:
        analysis_cache[key] = (now, setup)
    return setup


def _setup_for(symbol, timeframe):
    return _cached_setup(
        ("binance", symbol, timeframe),
        lambda: _closed_candles(symbol, timeframe),
    )


def _cell(symbol, timeframe, price):
    try:
        setup = _setup_for(symbol, timeframe)
        if setup is None:
            return {"status": "—", "price": price, "error": None, "no_signal": True}
        return store.evaluate(symbol, timeframe, setup, price)
    except Exception as exc:
        app.logger.warning("Failed %s %s: %s", symbol, timeframe, exc)
        return {"status": "!", "price": price, "error": str(exc)}


def _mt5_cell(symbol, timeframe, price):
    try:
        setup = _cached_setup(
            ("mt5", symbol, timeframe),
            lambda: mt5_data.closed_candles(symbol, timeframe, KLINE_LIMIT),
        )
        if setup is None:
            return {"status": "—", "price": price, "error": None, "no_signal": True}
        return store.evaluate(f"MT5:{symbol}", timeframe, setup, price)
    except Exception as exc:
        app.logger.warning("MT5 failed %s %s: %s", symbol, timeframe, exc)
        return {"status": "!", "price": price, "error": str(exc)}


def _smc_result(signal, price):
    signal = _recent_smc_signal(signal)
    if signal is None:
        return {"status": "—", "price": price, "no_signal": True}
    return {
        "status": signal.direction,
        "price": price,
        "entry": signal.entry,
        "take_profit": signal.take_profit,
        "stop_loss": signal.stop_loss,
        "rr": signal.rr,
        "grade": signal.grade,
        "timestamp": signal.timestamp,
        "zone_top": signal.zone_top,
        "zone_bottom": signal.zone_bottom,
    }


def _recent_smc_signal(signal):
    max_age_ms = max(
        1, int(os.getenv("SMC_SIGNAL_MAX_AGE_HOURS", "24"))
    ) * 3_600_000
    if signal is not None and int(time.time() * 1000) - signal.timestamp > max_age_ms:
        return None
    return signal


def _cached_smc(key, loader):
    now = time.monotonic()
    with cache_lock:
        cached = smc_cache.get(key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    minute, ob, trend = loader()
    signal = calculate_smc_signal(
        minute,
        ob,
        trend,
        max_age_hours=max(1, int(os.getenv("SMC_SIGNAL_MAX_AGE_HOURS", "24"))),
    )
    with cache_lock:
        smc_cache[key] = (now, signal)
    return signal


def _smc_binance_cell(symbol, price):
    try:
        signal = _cached_smc(
            ("binance", symbol),
            lambda: (
                _closed_candles(symbol, "1m"),
                _closed_candles(symbol, "5m"),
                _closed_candles(symbol, "15m"),
            ),
        )
        return _smc_result(signal, price)
    except Exception as exc:
        app.logger.warning("SMC Binance failed %s: %s", symbol, exc)
        return {"status": "!", "price": price, "error": str(exc)}


def _smc_mt5_cell(symbol, price):
    try:
        signal = _cached_smc(
            ("mt5", symbol),
            lambda: (
                mt5_data.closed_candles(symbol, "1m", KLINE_LIMIT),
                mt5_data.closed_candles(symbol, "5m", KLINE_LIMIT),
                mt5_data.closed_candles(symbol, "15m", KLINE_LIMIT),
            ),
        )
        return _smc_result(signal, price)
    except Exception as exc:
        app.logger.warning("SMC MT5 failed %s: %s", symbol, exc)
        return {"status": "!", "price": price, "error": str(exc)}


@app.get("/")
def dashboard():
    return render_template(
        "index.html",
        timeframes=TIMEFRAMES,
        refresh_seconds=max(15, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "30"))),
    )


@app.get("/smc")
def smc_dashboard():
    return render_template(
        "smc.html",
        refresh_seconds=max(15, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "30"))),
    )


@app.get("/confluence")
def confluence_dashboard():
    return render_template(
        "confluence.html",
        refresh_seconds=max(15, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "30"))),
    )


def _populate_rows(symbols, prices, cell_function, max_workers):
    rows = {
        symbol["exchange"]: {
            "symbol": symbol["exchange"],
            "display": symbol["display"],
            "price": prices.get(symbol["exchange"]),
            "timeframes": {},
        }
        for symbol in symbols
    }
    jobs = {}
    with ThreadPoolExecutor(
        max_workers=min(max_workers, max(1, len(symbols) * len(TIMEFRAMES)))
    ) as pool:
        for symbol in symbols:
            price = prices.get(symbol["exchange"])
            if price is None:
                for timeframe in TIMEFRAMES:
                    rows[symbol["exchange"]]["timeframes"][timeframe] = {
                        "status": "!",
                        "error": "ไม่พบราคาคู่นี้",
                    }
                continue
            for timeframe in TIMEFRAMES:
                future = pool.submit(
                    cell_function, symbol["exchange"], timeframe, price
                )
                jobs[future] = (symbol["exchange"], timeframe)
        for future in as_completed(jobs):
            symbol, timeframe = jobs[future]
            rows[symbol]["timeframes"][timeframe] = future.result()
    return list(rows.values())


def _populate_smc_rows(symbols, prices, cell_function, max_workers):
    rows = {
        symbol["exchange"]: {
            "symbol": symbol["exchange"],
            "display": symbol["display"],
            "price": prices.get(symbol["exchange"]),
        }
        for symbol in symbols
    }
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(symbols)))) as pool:
        jobs = {
            pool.submit(cell_function, symbol["exchange"], prices.get(symbol["exchange"])): symbol["exchange"]
            for symbol in symbols
            if prices.get(symbol["exchange"]) is not None
        }
        for future in as_completed(jobs):
            symbol = jobs[future]
            rows[symbol].update(future.result())
    return list(rows.values())


def _crypto_dashboard():
    symbols = _market_symbols()
    return _populate_rows(symbols, _current_prices(symbols), _cell, 20)


def _forex_dashboard():
    symbols = (
        mt5_data.market_watch_symbols()
        if MT5_USE_MARKET_WATCH
        else mt5_data.resolve_symbols(FOREX_SYMBOLS)
    )
    prices = {item["exchange"]: mt5_data.current_price(item["exchange"]) for item in symbols}
    rows = _populate_rows(symbols, prices, _mt5_cell, 8)
    for row in rows:
        row["trading_hours"] = sessions_for_symbol(row["display"])
    return rows


def _smc_crypto_dashboard():
    symbols = _market_symbols()
    prices = _current_prices(symbols)
    return _populate_smc_rows(symbols, prices, _smc_binance_cell, 20)


def _smc_forex_dashboard():
    symbols = (
        mt5_data.market_watch_symbols()
        if MT5_USE_MARKET_WATCH
        else mt5_data.resolve_symbols(FOREX_SYMBOLS)
    )
    prices = {item["exchange"]: mt5_data.current_price(item["exchange"]) for item in symbols}
    rows = _populate_smc_rows(symbols, prices, _smc_mt5_cell, 8)
    for row in rows:
        row["trading_hours"] = sessions_for_symbol(row["display"])
    return rows


def _matching_fibo_zones(signal, setup_loader):
    signal = _recent_smc_signal(signal)
    if signal is None:
        return []
    matches = []
    for timeframe in TIMEFRAMES:
        setup = setup_loader(timeframe)
        if setup is not None and setup.zone_low <= signal.entry <= setup.zone_high:
            matches.append(
                {
                    "timeframe": timeframe,
                    "fibo_direction": setup.direction,
                    "zone_low": setup.zone_low,
                    "zone_high": setup.zone_high,
                    "fibo_confirmed_at": setup.confirmed_at,
                }
            )
    return matches


def _confluence_rows(symbols, prices, smc_loader, setup_loader, max_workers):
    def scan(symbol):
        exchange = symbol["exchange"]
        price = prices.get(exchange)
        if price is None:
            return []
        try:
            signal = smc_loader(exchange)
            matches = _matching_fibo_zones(
                signal, lambda timeframe: setup_loader(exchange, timeframe)
            )
        except Exception as exc:
            app.logger.warning("Confluence failed %s: %s", exchange, exc)
            return []
        return [
            {
                "symbol": exchange,
                "display": symbol["display"],
                "price": price,
                "status": signal.direction,
                "entry": signal.entry,
                "take_profit": signal.take_profit,
                "stop_loss": signal.stop_loss,
                "rr": signal.rr,
                "grade": signal.grade,
                "timestamp": signal.timestamp,
                **match,
            }
            for match in matches
        ]

    rows = []
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(symbols)))) as pool:
        jobs = [pool.submit(scan, symbol) for symbol in symbols]
        for future in as_completed(jobs):
            rows.extend(future.result())
    return sorted(rows, key=lambda row: row["timestamp"], reverse=True)


def _confluence_crypto_dashboard():
    symbols = _market_symbols()
    prices = _current_prices(symbols)
    return _confluence_rows(
        symbols,
        prices,
        lambda symbol: _cached_smc(
            ("binance", symbol),
            lambda: (
                _closed_candles(symbol, "1m"),
                _closed_candles(symbol, "5m"),
                _closed_candles(symbol, "15m"),
            ),
        ),
        _setup_for,
        20,
    )


def _confluence_forex_dashboard():
    symbols = (
        mt5_data.market_watch_symbols()
        if MT5_USE_MARKET_WATCH
        else mt5_data.resolve_symbols(FOREX_SYMBOLS)
    )
    prices = {item["exchange"]: mt5_data.current_price(item["exchange"]) for item in symbols}
    rows = _confluence_rows(
        symbols,
        prices,
        lambda symbol: _cached_smc(
            ("mt5", symbol),
            lambda: (
                mt5_data.closed_candles(symbol, "1m", KLINE_LIMIT),
                mt5_data.closed_candles(symbol, "5m", KLINE_LIMIT),
                mt5_data.closed_candles(symbol, "15m", KLINE_LIMIT),
            ),
        ),
        lambda symbol, timeframe: _cached_setup(
            ("mt5", symbol, timeframe),
            lambda: mt5_data.closed_candles(symbol, timeframe, KLINE_LIMIT),
        ),
        8,
    )
    for row in rows:
        row["trading_hours"] = sessions_for_symbol(row["display"])
    return rows


@app.get("/api/crypto")
def crypto_data():
    try:
        rows = _crypto_dashboard()
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "timeframes": TIMEFRAMES,
                "rows": rows,
            }
        )
    except Exception as exc:
        return jsonify({"error": f"โหลดราคาจาก Binance ไม่สำเร็จ: {exc}"}), 502


@app.get("/api/forex")
def forex_data():
    try:
        rows = _forex_dashboard()
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "timeframes": TIMEFRAMES,
                "rows": rows,
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "timeframes": TIMEFRAMES,
                "rows": [],
                "error": str(exc),
            }
        )


@app.get("/api/smc/crypto")
def smc_crypto_data():
    try:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "rows": _smc_crypto_dashboard(),
            }
        )
    except Exception as exc:
        return jsonify({"error": f"โหลด SMC Crypto ไม่สำเร็จ: {exc}"}), 502


@app.get("/api/smc/forex")
def smc_forex_data():
    try:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "rows": _smc_forex_dashboard(),
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "rows": [],
                "error": str(exc),
            }
        )


@app.get("/api/confluence/crypto")
def confluence_crypto_data():
    try:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "rows": _confluence_crypto_dashboard(),
            }
        )
    except Exception as exc:
        return jsonify({"error": f"โหลด Confluence Crypto ไม่สำเร็จ: {exc}"}), 502


@app.get("/api/confluence/forex")
def confluence_forex_data():
    try:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "rows": _confluence_forex_dashboard(),
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "rows": [],
                "error": str(exc),
            }
        )


@app.get("/api/events")
def events_data():
    try:
        items = altfins_feed.get_feed()
        cache_info = altfins_feed.cache_info()
        return jsonify(
            {
                "updated_at": cache_info["updated_at"],
                "next_refresh_at": cache_info["next_refresh_at"],
                "items": items,
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "updated_at": int(time.time() * 1000),
                "items": [],
                "error": str(exc),
            }
        )


@app.get("/api/dashboard")
def dashboard_data():
    try:
        crypto_rows = _crypto_dashboard()
    except Exception as exc:
        return jsonify({"error": f"โหลดราคาจาก Binance ไม่สำเร็จ: {exc}"}), 502

    forex_error = None
    try:
        forex_rows = _forex_dashboard()
    except Exception as exc:
        forex_rows = []
        forex_error = str(exc)

    return jsonify(
        {
            "updated_at": int(time.time() * 1000),
            "timeframes": TIMEFRAMES,
            "rows": crypto_rows,
            "crypto_rows": crypto_rows,
            "forex_rows": forex_rows,
            "forex_error": forex_error,
        }
    )


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)