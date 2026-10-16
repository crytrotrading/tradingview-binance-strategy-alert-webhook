from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mt5_provider import Mt5MarketData


class FakeMt5:
    TIMEFRAME_M1 = 1

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def symbols_get(self):
        return [
            SimpleNamespace(name="EURUSDc", visible=True),
            SimpleNamespace(name="XAUUSDc", visible=True),
            SimpleNamespace(name="HIDDENc", visible=False),
        ]

    def symbol_select(self, symbol, enabled):
        return enabled

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=1.2345, last=0.0, ask=1.2347)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        return [
            {"time": 1, "open": 1.05, "high": 1.2, "low": 1.0, "close": 1.1, "tick_volume": 10},
            {"time": 2, "open": 1.15, "high": 1.3, "low": 1.1, "close": 1.2, "tick_volume": 12},
            {"time": 3, "open": 1.25, "high": 1.4, "low": 1.2, "close": 1.3, "tick_volume": 8},
        ]

    def last_error(self):
        return (0, "ok")


class Mt5MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("mt5_provider.mt5", FakeMt5())
        self.patcher.start()
        self.provider = Mt5MarketData()

    def tearDown(self):
        self.patcher.stop()

    def test_resolves_windsor_c_suffix_automatically(self):
        self.assertEqual(
            self.provider.resolve_symbols(["EURUSD", "XAUUSD", "MISSING"]),
            [
                {"display": "EURUSD", "exchange": "EURUSDc"},
                {"display": "XAUUSD", "exchange": "XAUUSDc"},
            ],
        )

    def test_reads_bid_and_excludes_forming_candle(self):
        self.assertEqual(self.provider.current_price("EURUSDc"), 1.2345)
        candles = self.provider.closed_candles("EURUSDc", "1m", 2)
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[-1].open_time, 2000)

    def test_returns_all_visible_market_watch_symbols(self):
        self.assertEqual(
            self.provider.market_watch_symbols(),
            [
                {"display": "EURUSD", "exchange": "EURUSDc"},
                {"display": "XAUUSD", "exchange": "XAUUSDc"},
            ],
        )

    @patch("mt5_provider.time.monotonic", return_value=100)
    @patch("mt5_provider.time.time", return_value=1_000)
    def test_detects_windsor_server_utc_offset(self, _time, _monotonic):
        tick = SimpleNamespace(time=1_000 + 3 * 3600)
        self.assertEqual(self.provider._remember_time_offset(tick), 3 * 3600)

    def test_allows_explicit_server_offset_override(self):
        with patch.dict("os.environ", {"MT5_SERVER_UTC_OFFSET_HOURS": "2"}):
            self.assertEqual(
                self.provider._remember_time_offset(SimpleNamespace(time=0)),
                2 * 3600,
            )


if __name__ == "__main__":
    unittest.main()
