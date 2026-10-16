import unittest

from signal_engine import Candle
from xsto_engine import _candidate_zones, _stochastic, calculate_xsto_signal


def candle(index, open_price, high, low, close, minutes=5):
    return Candle(
        open_time=index * minutes * 60_000,
        high=high,
        low=low,
        close=close,
        volume=100,
        open=open_price,
    )


class XstoEngineTests(unittest.TestCase):
    def test_detects_confirmed_m5_buy_zone(self):
        candles = [
            candle(index, 100, 101, 99, 100)
            for index in range(35)
        ]
        candles[20] = candle(20, 100, 101.5, 97.5, 99)
        candles[21] = candle(21, 99, 102.5, 98.5, 102)
        candles[22] = candle(22, 102, 105.5, 102, 105)
        candles[23] = candle(23, 105, 107, 104.5, 106.5)

        zones = _candidate_zones(candles)

        self.assertTrue(any(zone.side == 1 for zone in zones))
        zone = next(zone for zone in zones if zone.side == 1)
        self.assertGreaterEqual(zone.top - zone.bottom, 1.5 * 2)

    def test_stochastic_stays_within_bounds(self):
        candles = [
            candle(index, 100 + index, 101 + index, 99 + index, 100.5 + index, 1)
            for index in range(20)
        ]
        k, d = _stochastic(candles)
        self.assertTrue(all(0 <= value <= 100 for value in k if value is not None))
        self.assertTrue(all(0 <= value <= 100 for value in d if value is not None))

    def test_requires_enough_m15_history(self):
        minute = [candle(index, 100, 101, 99, 100, 1) for index in range(30)]
        m5 = [candle(index, 100, 101, 99, 100) for index in range(30)]
        m15 = [candle(index, 100, 101, 99, 100, 15) for index in range(199)]
        self.assertIsNone(calculate_xsto_signal(minute, m5, m15))


if __name__ == "__main__":
    unittest.main()
