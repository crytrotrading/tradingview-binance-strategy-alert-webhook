"""Read-only market data adapter for a locally running MetaTrader 5 terminal."""

from __future__ import annotations

import os
from threading import Lock

from signal_engine import Candle

try:
    import MetaTrader5 as mt5
except ImportError:  # MetaTrader5 only ships Windows wheels.
    mt5 = None


TIMEFRAME_NAMES = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}


class Mt5MarketData:
    def __init__(self) -> None:
        self._lock = Lock()
        self._resolved: dict[str, str] = {}

    def connect(self) -> None:
        if mt5 is None:
            raise RuntimeError("ยังไม่ได้ติดตั้ง MetaTrader5: py -m pip install MetaTrader5")
        with self._lock:
            terminal = mt5.terminal_info()
            if terminal is not None and terminal.connected:
                return
            path = os.getenv("MT5_PATH")
            connected = mt5.initialize(path=path) if path else mt5.initialize()
            if not connected:
                raise RuntimeError(f"เชื่อมต่อ MT5 ไม่สำเร็จ: {mt5.last_error()}")

    def resolve_symbols(self, requested: list[str]) -> list[dict[str, str]]:
        self.connect()
        with self._lock:
            available = list(mt5.symbols_get() or [])
            if not available:
                raise RuntimeError(f"ไม่พบ Symbols จาก MT5: {mt5.last_error()}")

            output = []
            for base in requested:
                cached = self._resolved.get(base)
                if cached and any(item.name == cached for item in available):
                    output.append({"display": base, "exchange": cached})
                    continue

                upper = base.upper()
                candidates = [
                    item
                    for item in available
                    if item.name.upper() == upper
                    or item.name.upper().startswith(upper)
                ]
                candidates.sort(
                    key=lambda item: (
                        item.name.upper() != upper,
                        not item.visible,
                        len(item.name),
                        item.name,
                    )
                )
                if not candidates:
                    continue
                selected = candidates[0].name
                if not mt5.symbol_select(selected, True):
                    continue
                self._resolved[base] = selected
                output.append({"display": base, "exchange": selected})
            return output

    def current_price(self, symbol: str) -> float:
        self.connect()
        with self._lock:
            tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"ไม่พบราคาของ {symbol}: {mt5.last_error()}")
        return float(tick.bid or tick.last or tick.ask)

    def closed_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        self.connect()
        mt5_timeframe = getattr(mt5, TIMEFRAME_NAMES[timeframe])
        with self._lock:
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, limit + 1)
        if rates is None or len(rates) < 2:
            raise RuntimeError(f"แท่งราคา {symbol} {timeframe} ไม่เพียงพอ: {mt5.last_error()}")

        # Position 0 is the currently forming candle. Signals use closed candles only.
        return [
            Candle(
                open_time=int(rate["time"]) * 1000,
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                volume=float(rate["tick_volume"] or 1),
            )
            for rate in rates[:-1]
        ]
