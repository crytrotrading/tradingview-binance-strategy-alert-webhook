"""Server-side scanner for the supplied xSTO Manual Rebuild v1.0.1 defaults."""

from __future__ import annotations

from dataclasses import dataclass

from signal_engine import Candle


MINUTE_MS = 60_000
M5_MS = 5 * MINUTE_MS
M15_MS = 15 * MINUTE_MS


@dataclass
class XstoZone:
    side: int
    top: float
    bottom: float
    source_index: int
    created_at: int
    created_index: int = 0
    last_touch: int = -100_000
    pending_at: int | None = None
    extreme_seen: bool = False


@dataclass(frozen=True)
class XstoSignal:
    direction: str
    entry: float
    take_profit: float
    stop_loss: float
    rr: float
    timestamp: int
    zone_top: float
    zone_bottom: float


def _open(candle: Candle) -> float:
    return candle.open if candle.open is not None else candle.close


def _ema(values: list[float], length: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < length:
        return output
    value = sum(values[:length]) / length
    output[length - 1] = value
    alpha = 2.0 / (length + 1)
    for index in range(length, len(values)):
        value = alpha * values[index] + (1.0 - alpha) * value
        output[index] = value
    return output


def _sma(values: list[float | None], length: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        if all(value is not None for value in window):
            output[index] = sum(window) / length  # type: ignore[arg-type]
    return output


def _atr(candles: list[Candle], length: int = 14) -> list[float | None]:
    ranges = []
    for index, candle in enumerate(candles):
        previous = candles[index - 1].close if index else candle.close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous),
                abs(candle.low - previous),
            )
        )
    output: list[float | None] = [None] * len(candles)
    if len(candles) < length:
        return output
    value = sum(ranges[:length]) / length
    output[length - 1] = value
    for index in range(length, len(candles)):
        value = (value * (length - 1) + ranges[index]) / length
        output[index] = value
    return output


def _stochastic(candles: list[Candle]) -> tuple[list[float | None], list[float | None]]:
    raw: list[float | None] = [None] * len(candles)
    for index in range(4, len(candles)):
        window = candles[index - 4 : index + 1]
        highest = max(candle.high for candle in window)
        lowest = min(candle.low for candle in window)
        raw[index] = (
            0.0
            if highest == lowest
            else (candles[index].close - lowest) * 100 / (highest - lowest)
        )
    k = _sma(raw, 3)
    return k, _sma(k, 3)


def _candidate_zones(candles: list[Candle]) -> list[XstoZone]:
    """Rebuild confirmed M5 candidates using the package's default inputs."""
    atr = _atr(candles)
    candidates: list[XstoZone] = []
    for source in range(14, len(candles) - 4):
        zone_atr = atr[source]
        if zone_atr is None:
            continue
        for side in (1, -1):
            opposite = (
                candles[source].close < _open(candles[source])
                if side == 1
                else candles[source].close > _open(candles[source])
            )
            if not opposite:
                continue

            run = 0
            for offset in range(1, min(40, len(candles) - source - 1) + 1):
                candle = candles[source + offset]
                in_direction = (
                    candle.close > _open(candle)
                    if side == 1
                    else candle.close < _open(candle)
                )
                if not in_direction:
                    break
                run += 1
            if run < 3:
                continue

            swing_window = candles[source - 3 : source + 4]
            if side == 1:
                swing_distance = candles[source].low - min(
                    candle.low for candle in swing_window
                )
            else:
                swing_distance = max(
                    candle.high for candle in swing_window
                ) - candles[source].high
            if swing_distance > 0.1 * zone_atr:
                continue

            top = candles[source].high
            bottom = candles[source].low
            fvg_offset = None
            for offset in range(2, run + 1):
                older = candles[source + offset - 2]
                newer = candles[source + offset]
                if side == 1:
                    gap_low, gap_high = older.high, newer.low
                    edge_distance = abs(gap_low - candles[source].high)
                else:
                    gap_low, gap_high = newer.high, older.low
                    edge_distance = abs(gap_high - candles[source].low)
                gap = gap_high - gap_low
                if (
                    gap > 0
                    and gap >= 0.2 * zone_atr
                    and edge_distance <= 0.1 * zone_atr
                ):
                    top = max(top, gap_high)
                    bottom = min(bottom, gap_low)
                    fvg_offset = offset
                    break
            if fvg_offset is None or top - bottom < 1.5 * zone_atr:
                continue

            confirmation_offset = max(3, fvg_offset) + 1
            confirmation = source + confirmation_offset
            if confirmation >= len(candles):
                continue
            broken = any(
                candle.close < bottom if side == 1 else candle.close > top
                for candle in candles[source + 1 : confirmation + 1]
            )
            if broken:
                continue
            candidates.append(
                XstoZone(
                    side=side,
                    top=top,
                    bottom=bottom,
                    source_index=source,
                    created_at=candles[confirmation].open_time + M5_MS,
                )
            )

    # Pine exports only the newest candidate for each side on a given M5 update.
    newest: dict[tuple[int, int], XstoZone] = {}
    for zone in candidates:
        key = (zone.created_at, zone.side)
        current = newest.get(key)
        if current is None or zone.source_index > current.source_index:
            newest[key] = zone
    return sorted(newest.values(), key=lambda zone: zone.created_at)


def _latest_closed_index(candles: list[Candle], close_time: int, duration: int) -> int:
    index = -1
    while (
        index + 1 < len(candles)
        and candles[index + 1].open_time + duration <= close_time
    ):
        index += 1
    return index


def calculate_xsto_signal(
    minute_candles: list[Candle],
    m5_candles: list[Candle],
    m15_candles: list[Candle],
    max_age_hours: int = 24,
) -> XstoSignal | None:
    if len(minute_candles) < 30 or len(m5_candles) < 20 or len(m15_candles) < 200:
        return None

    candidates = _candidate_zones(m5_candles)
    m5_atr = _atr(m5_candles)
    m15_atr = _atr(m15_candles)
    closes = [candle.close for candle in m15_candles]
    fast = _ema(closes, 50)
    slow = _ema(closes, 200)
    k, _ = _stochastic(minute_candles)

    zones: list[XstoZone] = []
    candidate_index = 0
    latest: XstoSignal | None = None

    for index, candle in enumerate(minute_candles):
        close_time = candle.open_time + MINUTE_MS
        m5_index = _latest_closed_index(m5_candles, close_time, M5_MS)
        m15_index = _latest_closed_index(m15_candles, close_time, M15_MS)
        if m5_index < 13 or m15_index < 199:
            continue
        current_m5_atr = m5_atr[m5_index]
        current_m15_atr = m15_atr[m15_index]
        current_fast = fast[m15_index]
        current_slow = slow[m15_index]
        if (
            current_m5_atr is None
            or current_m15_atr is None
            or current_fast is None
            or current_slow is None
        ):
            continue

        # Pine purges invalid/expired zones before accepting newly confirmed ones.
        zones = [
            zone
            for zone in zones
            if m5_index - zone.source_index < 192
            and (
                candle.close >= zone.bottom
                if zone.side == 1
                else candle.close <= zone.top
            )
        ]
        while (
            candidate_index < len(candidates)
            and candidates[candidate_index].created_at <= close_time
        ):
            candidate = candidates[candidate_index]
            gap_too_small = any(
                zone.side == candidate.side
                and max(
                    candidate.bottom - zone.top,
                    zone.bottom - candidate.top,
                )
                < 0.8 * current_m5_atr
                for zone in zones
            )
            if not gap_too_small:
                candidate.created_index = index
                zones.append(candidate)
                same_side = [zone for zone in zones if zone.side == candidate.side]
                if len(same_side) > 6:
                    zones.remove(same_side[0])
            candidate_index += 1

        trend = (
            1
            if m15_candles[m15_index].close > current_fast
            and m15_candles[m15_index].close > current_slow
            else -1
            if m15_candles[m15_index].close < current_fast
            and m15_candles[m15_index].close < current_slow
            else 0
        )
        distance_ok = (
            abs(m15_candles[m15_index].close - current_fast)
            <= 3.0 * current_m15_atr
        )
        current_k = k[index]
        previous_k = k[index - 1] if index else None
        if current_k is None:
            continue
        trigger_buy = (
            previous_k is not None and previous_k <= 20 and current_k > 20
        )
        trigger_sell = (
            previous_k is not None and previous_k >= 80 and current_k < 80
        )

        for zone in reversed(zones):
            touch = candle.low <= zone.top and candle.high >= zone.bottom
            old_enough = index - zone.created_index >= 2
            spaced = index - zone.last_touch >= 7
            if touch and old_enough and spaced:
                zone.last_touch = index
                zone.pending_at = index
                zone.extreme_seen = False
            if zone.pending_at is not None:
                if index - zone.pending_at > 20:
                    zone.pending_at = None
                    zone.extreme_seen = False
                else:
                    zone.extreme_seen = zone.extreme_seen or (
                        current_k <= 20 if zone.side == 1 else current_k >= 80
                    )
            trigger = trigger_buy if zone.side == 1 else trigger_sell
            ready = (
                zone.pending_at is not None
                and zone.extreme_seen
                and trigger
                and trend == zone.side
                and distance_ok
            )
            if not ready:
                continue
            stop = (
                zone.bottom - 0.3 * current_m5_atr
                if zone.side == 1
                else zone.top + 0.3 * current_m5_atr
            )
            risk = zone.side * (candle.close - stop)
            if risk < current_m5_atr:
                continue
            target = candle.close + zone.side * risk * 4.0
            latest = XstoSignal(
                direction="BUY" if zone.side == 1 else "SELL",
                entry=candle.close,
                take_profit=target,
                stop_loss=stop,
                rr=4.0,
                timestamp=close_time,
                zone_top=zone.top,
                zone_bottom=zone.bottom,
            )
            zone.pending_at = None
            zone.extreme_seen = False
            break

    if (
        latest is not None
        and minute_candles[-1].open_time + MINUTE_MS - latest.timestamp
        <= max_age_hours * 3_600_000
    ):
        return latest
    return None
