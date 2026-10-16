"""Server-side SMCxSTO V3.1 scanner using the Pine defaults."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from signal_engine import Candle


MINUTE_MS = 60_000
OB_MS = 5 * MINUTE_MS
TREND_MS = 15 * MINUTE_MS
SWING_TOLERANCE_ATR = 0.5


@dataclass
class Zone:
    top: float
    bottom: float
    atr: float
    bull: bool
    grade: str
    created_at: int
    created_index: int = 0
    armed: bool = False
    saw_extreme: bool = False
    saw_cross: bool = False
    blocked: bool = False
    last_touch: int = -100_000
    exit_index: int = -100_000
    inside_count: int = 0


@dataclass(frozen=True)
class SmcSignal:
    direction: str
    entry: float
    take_profit: float
    stop_loss: float
    rr: float
    grade: str
    timestamp: int
    zone_top: float
    zone_bottom: float


def _sma(values: list[float | None], length: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        if all(value is not None for value in window):
            output[index] = sum(window) / length  # type: ignore[arg-type]
    return output


def _ema(values: Iterable[float], length: int) -> list[float | None]:
    source = list(values)
    output: list[float | None] = [None] * len(source)
    if len(source) < length:
        return output
    current = sum(source[:length]) / length
    output[length - 1] = current
    alpha = 2.0 / (length + 1)
    for index in range(length, len(source)):
        current = alpha * source[index] + (1 - alpha) * current
        output[index] = current
    return output


def _atr(candles: list[Candle], length: int = 14) -> list[float | None]:
    true_ranges: list[float] = []
    for index, candle in enumerate(candles):
        if index == 0:
            true_ranges.append(candle.high - candle.low)
        else:
            previous = candles[index - 1].close
            true_ranges.append(
                max(candle.high - candle.low, abs(candle.high - previous), abs(candle.low - previous))
            )
    output: list[float | None] = [None] * len(candles)
    if len(candles) < length:
        return output
    current = sum(true_ranges[:length]) / length
    output[length - 1] = current
    for index in range(length, len(candles)):
        current = (current * (length - 1) + true_ranges[index]) / length
        output[index] = current
    return output


def _stochastic(candles: list[Candle]) -> tuple[list[float | None], list[float | None]]:
    raw: list[float | None] = [None] * len(candles)
    for index in range(4, len(candles)):
        window = candles[index - 4 : index + 1]
        highest = max(candle.high for candle in window)
        lowest = min(candle.low for candle in window)
        raw[index] = 0.0 if highest == lowest else (candles[index].close - lowest) * 100 / (highest - lowest)
    k = _sma(raw, 3)
    return k, _sma(k, 3)


def _is_pivot(candles: list[Candle], index: int, bull: bool, left: int = 5, right: int = 5) -> bool:
    if index < left or index + right >= len(candles):
        return False
    value = candles[index].low if bull else candles[index].high
    others = candles[index - left : index] + candles[index + 1 : index + right + 1]
    return all(value <= candle.low for candle in others) if bull else all(value >= candle.high for candle in others)


def _candidate_zones(candles: list[Candle]) -> list[Zone]:
    atr = _atr(candles)
    zones: list[Zone] = []
    swing_right = 5
    run_bars = 2
    for confirmed_index in range(10, len(candles)):
        index = confirmed_index - swing_right
        zone_atr = atr[index]
        if zone_atr is None or index + 2 >= len(candles):
            continue
        candle_open = lambda candle: candle.open if candle.open is not None else candle.close
        bull_opposite = candles[index].close < candle_open(candles[index])
        bear_opposite = candles[index].close > candle_open(candles[index])
        bull_run = all(candles[index + offset].close > candle_open(candles[index + offset]) for offset in range(1, run_bars + 1))
        bear_run = all(candles[index + offset].close < candle_open(candles[index + offset]) for offset in range(1, run_bars + 1))
        bull_gap = candles[index + 2].low - candles[index].high
        bear_gap = candles[index].low - candles[index + 2].high
        bull_fvg = bull_gap + 0.1 * zone_atr > 0 and bull_gap >= 0.15 * zone_atr
        bear_fvg = bear_gap + 0.1 * zone_atr > 0 and bear_gap >= 0.15 * zone_atr
        bull_c1, bear_c1 = bull_opposite and bull_run, bear_opposite and bear_run
        bull_c2, bear_c2 = bull_opposite and bull_fvg, bear_opposite and bear_fvg

        for bull, valid, grade, has_fvg in (
            (True, (bull_c1 or bull_c2) and _is_pivot(candles, index, True), "A" if bull_c1 and bull_c2 else "B", bull_c2),
            (False, (bear_c1 or bear_c2) and _is_pivot(candles, index, False), "A" if bear_c1 and bear_c2 else "B", bear_c2),
        ):
            if not valid:
                continue
            top, bottom = candles[index].high, candles[index].low
            if bull and has_fvg:
                top = max(top, candles[index + 2].low)
            if not bull and has_fvg:
                bottom = min(bottom, candles[index + 2].high)
            # V3.1 expands both POI edges using Swing tolerance before
            # minimum-height and spacing checks.
            top += SWING_TOLERANCE_ATR * zone_atr
            bottom -= SWING_TOLERANCE_ATR * zone_atr
            if top - bottom < 0.5 * zone_atr:
                continue
            created_at = candles[confirmed_index].open_time + OB_MS
            zones.append(Zone(top, bottom, zone_atr, bull, grade, created_at))
    return zones


def _trend_series(candles: list[Candle]):
    fast = _ema((candle.close for candle in candles), 50)
    slow = _ema((candle.close for candle in candles), 200)
    atr = _atr(candles)
    return fast, slow, atr


def calculate_smc_signal(
    minute_candles: list[Candle],
    ob_candles: list[Candle],
    trend_candles: list[Candle],
    max_age_hours: int = 24,
) -> SmcSignal | None:
    if len(minute_candles) < 30 or len(ob_candles) < 30 or len(trend_candles) < 201:
        return None

    candidates = _candidate_zones(ob_candles)
    sto_k, sto_d = _stochastic(minute_candles)
    trend_fast, trend_slow, trend_atr = _trend_series(trend_candles)
    zones: list[Zone] = []
    candidate_index = 0
    trend_index = 199
    last_signal_index = -100_000
    latest: SmcSignal | None = None

    for index, candle in enumerate(minute_candles):
        candle_close_time = candle.open_time + MINUTE_MS
        while candidate_index < len(candidates) and candidates[candidate_index].created_at <= candle_close_time:
            candidate = candidates[candidate_index]
            candidate.created_index = index
            center = (candidate.top + candidate.bottom) / 2
            too_close = any(
                zone.bull == candidate.bull
                and abs(center - (zone.top + zone.bottom) / 2) < 0.8 * candidate.atr
                for zone in zones
            )
            if not too_close:
                zones.append(candidate)
                same_side = [zone for zone in zones if zone.bull == candidate.bull]
                if len(same_side) > 6:
                    zones.remove(same_side[0])
            candidate_index += 1

        while (
            trend_index + 1 < len(trend_candles)
            and trend_candles[trend_index + 1].open_time + TREND_MS <= candle.open_time
        ):
            trend_index += 1
        fast = trend_fast[trend_index]
        slow = trend_slow[trend_index]
        trend_a = trend_atr[trend_index]
        trend_close = trend_candles[trend_index].close
        if fast is None or slow is None or trend_a is None:
            continue
        bull_trend = fast > slow and trend_close > slow
        bear_trend = fast < slow and trend_close < slow
        distance_pass = abs(trend_close - fast) <= trend_a * 2.5

        sample = index - 1  # Pine confirmed STO uses the previously closed STO candle.
        k = sto_k[sample] if sample >= 0 else None
        d = sto_d[sample] if sample >= 0 else None
        previous_k = sto_k[sample - 1] if sample > 0 else None
        previous_d = sto_d[sample - 1] if sample > 0 else None
        if k is None or d is None:
            continue
        bull_cross = previous_k is not None and previous_d is not None and previous_k <= previous_d and k > d
        bear_cross = previous_k is not None and previous_d is not None and previous_k >= previous_d and k < d

        for zone in list(reversed(zones)):
            if (candle_close_time - zone.created_at) // OB_MS > 194:
                zones.remove(zone)
                continue
            broken = candle.close < zone.bottom if zone.bull else candle.close > zone.top
            inside = candle.low <= zone.top and candle.high >= zone.bottom
            zone.inside_count = zone.inside_count + 1 if inside else 0
            if broken or zone.inside_count > 100:
                zones.remove(zone)
                continue
            if zone.inside_count > 100:
                zone.blocked = True
            can_retouch = index - zone.last_touch >= 20
            mature = index - zone.created_index >= 1
            if inside and mature and can_retouch:
                zone.armed = True
                zone.last_touch = index
                zone.exit_index = -100_000
            if zone.armed and not inside and zone.exit_index < 0:
                zone.exit_index = index
            if zone.exit_index >= 0 and index - zone.exit_index > 12:
                zone.armed = zone.saw_extreme = zone.saw_cross = False

            extreme = k < 30 if zone.bull else k > 70
            if zone.armed and extreme:
                zone.saw_extreme = True
            cross = bull_cross if zone.bull else bear_cross
            if zone.armed and cross:
                zone.saw_cross = True
            crossed_outside = zone.saw_cross and (k > 30 if zone.bull else k < 70)
            location_pass = (
                candle.close <= zone.top + zone.atr
                and candle.close >= zone.bottom - zone.atr
            )
            trend_pass = bull_trend if zone.bull else bear_trend
            atr_relevant = trend_close >= fast if zone.bull else trend_close <= fast
            atr_pass = not atr_relevant or distance_pass
            cooldown_pass = index - last_signal_index >= 15
            ready = (
                not zone.blocked
                and zone.armed
                and zone.saw_extreme
                and crossed_outside
                and location_pass
                and trend_pass
                and atr_pass
                and cooldown_pass
            )
            if ready:
                stop = zone.bottom - 0.3 * zone.atr if zone.bull else zone.top + 0.3 * zone.atr
                risk = abs(candle.close - stop)
                take_profit = candle.close + risk * 2.5 if zone.bull else candle.close - risk * 2.5
                latest = SmcSignal(
                    "BUY" if zone.bull else "SELL",
                    candle.close,
                    take_profit,
                    stop,
                    2.5,
                    zone.grade,
                    candle_close_time,
                    zone.top,
                    zone.bottom,
                )
                last_signal_index = index
                zone.armed = zone.saw_extreme = zone.saw_cross = False
                break

    if latest and minute_candles[-1].open_time + MINUTE_MS - latest.timestamp <= max_age_hours * 3_600_000:
        return latest
    return None
