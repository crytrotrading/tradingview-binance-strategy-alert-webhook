import os
import tempfile
import unittest

from app import _rank_markets, _with_pinned_markets
from signal_engine import RetestStore, Setup, tradingview_rsi


def sample_setup(key_offset=0):
    return Setup(
        direction="BUY",
        b1=10,
        b2=20 + key_offset,
        r1=25.0,
        r2=28.0,
        fib0=100.0,
        fib100=200.0,
        entry=123.6,
        tp1=200.0,
        tp2=227.2,
        rr=3.2,
        score=0.4,
        reason="Bull Div",
        tp1_source="Fibo100",
        tp2_source="FiboExt",
        confirmed_at=123456,
    )


class RetestStoreTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp()
        os.close(handle)
        self.store = RetestStore(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_first_entry_exit_and_retest(self):
        setup = sample_setup()
        self.assertEqual(self.store.evaluate("BTCUSDT", "1h", setup, 110)["status"], "BUY")
        self.assertEqual(self.store.evaluate("BTCUSDT", "1h", setup, 130)["status"], "—")
        result = self.store.evaluate("BTCUSDT", "1h", setup, 120)
        self.assertEqual(result["status"], "BUY RETEST")
        self.assertTrue(result["is_retest"])

    def test_new_signal_resets_retest(self):
        old = sample_setup()
        self.store.evaluate("BTCUSDT", "4h", old, 110)
        self.store.evaluate("BTCUSDT", "4h", old, 130)
        result = self.store.evaluate("BTCUSDT", "4h", sample_setup(1), 110)
        self.assertEqual(result["status"], "BUY")

    def test_state_is_separate_per_timeframe(self):
        setup = sample_setup()
        self.store.evaluate("BTCUSDT", "1h", setup, 110)
        self.store.evaluate("BTCUSDT", "1h", setup, 130)
        self.assertEqual(self.store.evaluate("BTCUSDT", "4h", setup, 110)["status"], "BUY")


class RsiTests(unittest.TestCase):
    def test_rsi_bounds_and_length(self):
        result = tradingview_rsi(range(30), 14)
        self.assertEqual(len(result), 30)
        self.assertIsNone(result[13])
        self.assertEqual(result[14], 100.0)


class MarketRankingTests(unittest.TestCase):
    def test_ranks_usdt_markets_and_excludes_stables_and_leverage(self):
        payload = [
            {"symbol": "ETHUSDT", "quoteVolume": "900"},
            {"symbol": "BTCUSDT", "quoteVolume": "1000"},
            {"symbol": "USDCUSDT", "quoteVolume": "2000"},
            {"symbol": "BTCUPUSDT", "quoteVolume": "3000"},
            {"symbol": "ETHEUR", "quoteVolume": "5000"},
        ]
        self.assertEqual(
            _rank_markets(payload, 2),
            [
                {"display": "BTC", "exchange": "BTCUSDT"},
                {"display": "ETH", "exchange": "ETHUSDT"},
            ],
        )

    def test_pinned_market_stays_first_and_does_not_reduce_top_count(self):
        xau = {"display": "XAU", "exchange": "XAUTUSDT"}
        ranked = [
            {"display": "BTC", "exchange": "BTCUSDT"},
            xau,
            {"display": "ETH", "exchange": "ETHUSDT"},
        ]
        self.assertEqual(
            _with_pinned_markets(ranked, [xau], 2),
            [xau, ranked[0], ranked[2]],
        )


if __name__ == "__main__":
    unittest.main()
