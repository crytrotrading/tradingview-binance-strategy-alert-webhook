import unittest

from signal_engine import Candle
from smc_engine import _candidate_zones, _stochastic, calculate_smc_signal


def candle(index, open_price, high, low, close, minutes=5):
    return Candle(
        open_time=index * minutes * 60_000,
        high=high,
        low=low,
        close=close,
        volume=100,
        open=open_price,
    )


class SmcEngineTests(unittest.TestCase):
    def test_detects_confirmed_bullish_order_block(self):
        candles = [
            candle(index, 109, 110, 108, 109)
            for index in range(30)
        ]
        candles[10] = candle(10, 102, 102, 100, 101)
        candles[11] = candle(11, 102.5, 104, 102, 103.5)
        candles[12] = candle(12, 103.5, 105, 103, 104.5)
        zones = _candidate_zones(candles)
        self.assertTrue(any(zone.bull and zone.grade in {"A", "B"} for zone in zones))

    def test_stochastic_stays_within_bounds(self):
        candles = [
            candle(index, 100 + index, 101 + index, 99 + index, 100.5 + index, 1)
            for index in range(20)
        ]
        k, d = _stochastic(candles)
        self.assertTrue(all(0 <= value <= 100 for value in k if value is not None))
        self.assertTrue(all(0 <= value <= 100 for value in d if value is not None))

    def test_returns_no_signal_with_insufficient_history(self):
        candles = [candle(index, 100, 101, 99, 100, 1) for index in range(10)]
        self.assertIsNone(calculate_smc_signal(candles, candles, candles))


if __name__ == "__main__":
    unittest.main()
