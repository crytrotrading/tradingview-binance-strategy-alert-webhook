"""RSI/Fibonacci signal calculation and persistent zone/retest state."""

from __future__ import annotations

from dataclasses import dataclass
import math
import sqlite3
from threading import Lock
from typing import Iterable


@dataclass(frozen=True)
class Candle:
    open_time: int
    high: float
    low: float
    close: float
    volume: float
    open: float | None = None


@dataclass(frozen=True)
class Setup:
    direction: str
    b1: int
    b2: int
    r1: float
    r2: float
    fib0: float
    fib100: float
    entry: float
    tp1: float
    tp2: float
    rr: float
    score: float
    reason: str
    tp1_source: str
    tp2_source: str
    confirmed_at: int

    @property
    def key(self) -> str:
        return f"{self.direction}:{self.b1}:{self.b2}"

    @property
    def zone_low(self) -> float:
        return min(self.fib0, self.entry)

    @property
    def zone_high(self) -> float:
        return max(self.fib0, self.entry)


@dataclass(frozen=True)
class EngineConfig:
    rsi_length: int = 14
    buy_max: float = 30.99
    sell_min: float = 70.0
    pivot_left: int = 5
    pivot_right: int = 5
    max_pairs: int = 12
    entry_pct: float = 23.6
    extension_pct: float = 127.2
    value_area_pct: float = 70.0
    min_rr: float = 0.8
    profile_bins: int = 24
    use_volume_profile: bool = True


def classify_ema_trend(
    candles: list[Candle], fast_length: int = 50, slow_length: int = 200
) -> str:
    """Classify the latest closed candle using the SMC EMA trend rules."""
    if len(candles) < slow_length:
        return "SIDEWAY"

    closes = [candle.close for candle in candles]

    def latest_ema(length: int) -> float:
        value = sum(closes[:length]) / length
        alpha = 2.0 / (length + 1)
        for close in closes[length:]:
            value = alpha * close + (1.0 - alpha) * value
        return value

    fast = latest_ema(fast_length)
    slow = latest_ema(slow_length)
    close = candles[-1].close
    tolerance = max(abs(slow) * 1e-9, 1e-12)
    if fast > slow + tolerance and close > slow:
        return "UP"
    if fast < slow - tolerance and close < slow:
        return "DOWN"
    return "SIDEWAY"


def tradingview_rsi(closes: Iterable[float], length: int) -> list[float | None]:
    """Wilder RSI, equivalent to TradingView ta.rsi for normal price series."""
    values = list(closes)
    output: list[float | None] = [None] * len(values)
    if len(values) <= length:
        return output

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, length + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length

    def calculate() -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    output[length] = calculate()
    for i in range(length + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (length - 1) + max(change, 0.0)) / length
        avg_loss = (avg_loss * (length - 1) + max(-change, 0.0)) / length
        output[i] = calculate()
    return output


def _pivots(
    rsi: list[float | None], candles: list[Candle], left: int, right: int, low: bool
) -> list[tuple[float, int, float]]:
    result: list[tuple[float, int, float]] = []
    for index in range(left, len(rsi) - right):
        value = rsi[index]
        window = rsi[index - left : index + right + 1]
        if value is None or any(item is None for item in window):
            continue
        others = window[:left] + window[left + 1 :]
        is_pivot = all(value <= item for item in others) if low else all(value >= item for item in others)
        if is_pivot:
            price = candles[index].low if low else candles[index].high
            result.append((value, index, price))
    return result[-40:]


def _volume_profile(
    candles: list[Candle], start: int, end: int, cfg: EngineConfig
) -> tuple[float | None, float | None, float | None]:
    section = candles[start : end + 1]
    range_high = max(candle.high for candle in section)
    range_low = min(candle.low for candle in section)
    if range_high <= range_low:
        return None, None, None

    step = (range_high - range_low) / cfg.profile_bins
    volumes = [0.0] * cfg.profile_bins
    for candle in section:
        midpoint = (candle.high + candle.low) / 2.0
        index = min(cfg.profile_bins - 1, max(0, math.floor((midpoint - range_low) / step)))
        volumes[index] += candle.volume or 1.0

    poc_index = max(range(cfg.profile_bins), key=volumes.__getitem__)
    target = sum(volumes) * cfg.value_area_pct / 100.0
    accumulated = volumes[poc_index]
    low_index = high_index = poc_index
    while accumulated < target and (low_index > 0 or high_index < cfg.profile_bins - 1):
        volume_low = volumes[low_index - 1] if low_index > 0 else -1.0
        volume_high = volumes[high_index + 1] if high_index < cfg.profile_bins - 1 else -1.0
        if volume_high >= volume_low and high_index < cfg.profile_bins - 1:
            high_index += 1
            accumulated += volumes[high_index]
        elif low_index > 0:
            low_index -= 1
            accumulated += volumes[low_index]

    level = lambda index: range_low + (index + 0.5) * step
    return level(low_index), level(poc_index), level(high_index)


def _targets(
    direction: str,
    entry: float,
    fib0: float,
    fib100: float,
    profile: tuple[float | None, float | None, float | None],
    cfg: EngineConfig,
) -> tuple[float, float, str, str]:
    value_low, poc, value_high = profile
    tagged = [("VAL", value_low), ("POC", poc), ("VAH", value_high)]
    if direction == "BUY":
        eligible = sorted(((tag, value) for tag, value in tagged if value is not None and value > entry), key=lambda x: x[1])
        level = lambda pct: fib0 + (fib100 - fib0) * pct / 100.0
        tp1, source1 = (eligible[0][1], eligible[0][0]) if eligible else (level(100.0), "Fibo100")
        if len(eligible) >= 2:
            tp2, source2 = eligible[1][1], eligible[1][0]
        else:
            extension = level(cfg.extension_pct)
            tp2, source2 = (extension if extension > tp1 else level(161.8)), "FiboExt"
    else:
        eligible = sorted(
            ((tag, value) for tag, value in tagged if value is not None and value < entry),
            key=lambda x: x[1],
            reverse=True,
        )
        level = lambda pct: fib0 - (fib0 - fib100) * pct / 100.0
        tp1, source1 = (eligible[0][1], eligible[0][0]) if eligible else (level(100.0), "Fibo100")
        if len(eligible) >= 2:
            tp2, source2 = eligible[1][1], eligible[1][0]
        else:
            extension = level(cfg.extension_pct)
            tp2, source2 = (extension if extension < tp1 else level(161.8)), "FiboExt"
    return tp1, tp2, source1, source2


def _scan(candles: list[Candle], pivots: list[tuple[float, int, float]], direction: str, cfg: EngineConfig) -> Setup | None:
    best: Setup | None = None
    candidates = pivots[-cfg.max_pairs :]
    for first in range(len(candidates) - 1):
        for second in range(first + 1, len(candidates)):
            r1, b1, p1 = candidates[first]
            r2, b2, p2 = candidates[second]
            if direction == "BUY":
                both = r1 <= cfg.buy_max and r2 <= cfg.buy_max
                divergence = p2 < p1 and r2 > r1
                one = r1 <= cfg.buy_max or r2 <= cfg.buy_max
            else:
                both = r1 >= cfg.sell_min and r2 >= cfg.sell_min
                divergence = p2 > p1 and r2 < r1
                one = r1 >= cfg.sell_min or r2 >= cfg.sell_min
            if not (both or (divergence and one)):
                continue

            section = candles[b1 : b2 + 1]
            low = min(min(candle.low for candle in section), p1, p2)
            high = max(max(candle.high for candle in section), p1, p2)
            if high <= low:
                continue

            fib0, fib100 = (low, high) if direction == "BUY" else (high, low)
            entry = low + (high - low) * cfg.entry_pct / 100.0 if direction == "BUY" else high - (high - low) * cfg.entry_pct / 100.0
            profile = _volume_profile(candles, b1, b2, cfg) if cfg.use_volume_profile else (None, None, None)
            tp1, tp2, source1, source2 = _targets(direction, entry, fib0, fib100, profile, cfg)
            risk = entry - low if direction == "BUY" else high - entry
            reward = tp1 - entry if direction == "BUY" else entry - tp1
            rr = reward / risk if risk > 0 else -1.0
            if rr < cfg.min_rr:
                continue

            if direction == "BUY":
                base_score = (max(0.0, cfg.buy_max - r1) + max(0.0, cfg.buy_max - r2)) / max(cfg.buy_max * 2.0, 0.01)
                reason = "Bull Div" if divergence else "2 Legs OS"
            else:
                denominator = max(100.0 - cfg.sell_min, 0.01)
                base_score = (max(0.0, r1 - cfg.sell_min) + max(0.0, r2 - cfg.sell_min)) / (denominator * 2.0)
                reason = "Bear Div" if divergence else "2 Legs OB"
            score = base_score + (0.2 if divergence else 0.0) + (0.15 if source1 == "POC" else 0.0)
            setup = Setup(
                direction, candles[b1].open_time, candles[b2].open_time,
                r1, r2, fib0, fib100, entry, tp1, tp2,
                rr, score, reason, source1, source2, candles[min(b2 + cfg.pivot_right, len(candles) - 1)].open_time,
            )
            if best is None or rr + score + second * 0.0001 > best.rr + best.score:
                best = setup
    return best


def calculate_setup(candles: list[Candle], cfg: EngineConfig | None = None) -> Setup | None:
    cfg = cfg or EngineConfig()
    if len(candles) < cfg.rsi_length + cfg.pivot_left + cfg.pivot_right + 2:
        return None
    rsi = tradingview_rsi((candle.close for candle in candles), cfg.rsi_length)
    buy = _scan(candles, _pivots(rsi, candles, cfg.pivot_left, cfg.pivot_right, True), "BUY", cfg)
    sell = _scan(candles, _pivots(rsi, candles, cfg.pivot_left, cfg.pivot_right, False), "SELL", cfg)
    if buy is None:
        return sell
    if sell is None:
        return buy
    return buy if (buy.rr, buy.score) >= (sell.rr, sell.score) else sell


class RetestStore:
    """SQLite-backed state, isolated by symbol and timeframe."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS signal_state (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    signal_key TEXT NOT NULL,
                    has_entered INTEGER NOT NULL DEFAULT 0,
                    has_exited INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (symbol, timeframe)
                )"""
            )

    def evaluate(self, symbol: str, timeframe: str, setup: Setup, price: float) -> dict:
        in_zone = setup.zone_low <= price <= setup.zone_high
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM signal_state WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe),
            ).fetchone()
            if row is None or row["signal_key"] != setup.key:
                entered, exited = (in_zone, False)
                connection.execute(
                    """INSERT INTO signal_state(symbol, timeframe, signal_key, has_entered, has_exited)
                       VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol, timeframe) DO UPDATE SET
                       signal_key=excluded.signal_key, has_entered=excluded.has_entered,
                       has_exited=excluded.has_exited""",
                    (symbol, timeframe, setup.key, int(entered), int(exited)),
                )
            else:
                entered, exited = bool(row["has_entered"]), bool(row["has_exited"])
                if in_zone:
                    entered = True
                elif entered:
                    exited = True
                connection.execute(
                    "UPDATE signal_state SET has_entered = ?, has_exited = ? WHERE symbol = ? AND timeframe = ?",
                    (int(entered), int(exited), symbol, timeframe),
                )

        status = f"{setup.direction} RETEST" if in_zone and exited else setup.direction if in_zone else "—"
        return {
            "status": status,
            "in_zone": in_zone,
            "is_retest": in_zone and exited,
            "direction": setup.direction,
            "price": price,
            "zone_low": setup.zone_low,
            "zone_high": setup.zone_high,
            "entry": setup.entry,
            "stop": setup.fib0,
            "tp1": setup.tp1,
            "tp2": setup.tp2,
            "rr": setup.rr,
            "reason": setup.reason,
            "signal_key": setup.key,
            "confirmed_at": setup.confirmed_at,
        }
