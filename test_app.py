import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app
from smc_engine import SmcSignal


class ProviderApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    @patch("app._crypto_dashboard", return_value=[{"symbol": "BTCUSDT"}])
    def test_crypto_endpoint_returns_independently(self, _dashboard):
        response = self.client.get("/api/crypto")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["rows"][0]["symbol"], "BTCUSDT")

    @patch("app._forex_dashboard", side_effect=RuntimeError("MT5 offline"))
    def test_forex_error_does_not_fail_request(self, _dashboard):
        response = self.client.get("/api/forex")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["error"], "MT5 offline")

    @patch("app.altfins_feed.get_feed", return_value=[{"title": "ข่าวสำคัญ"}])
    def test_events_endpoint_is_independent(self, _feed):
        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["title"], "ข่าวสำคัญ")

    @patch("app._smc_crypto_dashboard", return_value=[{"symbol": "BTCUSDT", "status": "BUY"}])
    def test_smc_crypto_endpoint(self, _dashboard):
        response = self.client.get("/api/smc/crypto")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["rows"][0]["status"], "BUY")

    @patch("app.time.time", return_value=100_000)
    def test_stale_smc_market_signal_is_hidden(self, _time):
        signal = SmcSignal("BUY", 100, 110, 96, 2.5, "A", 1, 102, 98)
        self.assertEqual(app._smc_result(signal, 100)["status"], "—")

    @patch("app.time.time", return_value=100)
    def test_confluence_requires_matching_direction_and_trend(self, _time):
        signal = SmcSignal("BUY", 100, 110, 96, 2.5, "A", 99_000, 102, 98)
        analyses = {
            "1m": (
                SimpleNamespace(
                    zone_low=99,
                    zone_high=101,
                    direction="BUY",
                    confirmed_at=90_000,
                ),
                "UP",
            ),
            "5m": (
                SimpleNamespace(
                    zone_low=99,
                    zone_high=101,
                    direction="SELL",
                    confirmed_at=80_000,
                ),
                "UP",
            ),
            "15m": (
                SimpleNamespace(
                    zone_low=99,
                    zone_high=101,
                    direction="BUY",
                    confirmed_at=70_000,
                ),
                "DOWN",
            ),
        }

        matches = app._matching_fibo_zones(
            signal, lambda timeframe: analyses.get(timeframe, (None, "SIDEWAY"))
        )

        self.assertEqual([match["timeframe"] for match in matches], ["1m"])
        self.assertEqual(matches[0]["zone_low"], 99)
        self.assertEqual(matches[0]["trend"], "UP")

    def test_confluence_score_rewards_grade_and_multiple_timeframes(self):
        grade_a = SmcSignal("BUY", 100, 110, 96, 2.5, "A", 99_000, 102, 98)
        grade_b = SmcSignal("BUY", 100, 110, 96, 2.5, "B", 99_000, 102, 98)
        self.assertGreater(
            app._confluence_score(grade_a, [{}, {}]),
            app._confluence_score(grade_b, [{}]),
        )

    def test_entry_state_uses_current_price_without_claiming_history(self):
        signal = SmcSignal("BUY", 100, 110, 96, 2.5, "A", 99_000, 102, 98)
        self.assertEqual(app._entry_state(signal, 105), "ABOVE_ENTRY")
        self.assertEqual(app._entry_state(signal, 110), "AT_TP")
        self.assertEqual(app._entry_state(signal, 96), "AT_SL")

    @patch("app.time.time", return_value=100)
    def test_confluence_groups_matching_timeframes_per_symbol(self, _time):
        signal = SmcSignal("BUY", 100, 110, 96, 2.5, "A", 99_000, 102, 98)
        setup = SimpleNamespace(
            zone_low=99,
            zone_high=101,
            direction="BUY",
            confirmed_at=90_000,
        )
        rows = app._confluence_rows(
            [{"display": "BTC", "exchange": "BTCUSDT"}],
            {"BTCUSDT": 105},
            lambda _symbol: signal,
            lambda _symbol, timeframe: (
                (setup, "UP") if timeframe in {"1h", "4h"} else (None, "SIDEWAY")
            ),
            1,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["timeframes"], ["1h", "4h"])
        self.assertEqual(len(rows[0]["matches"]), 2)

    @patch("app._confluence_crypto_dashboard", return_value=[{"symbol": "BTCUSDT"}])
    def test_confluence_crypto_endpoint(self, _dashboard):
        response = self.client.get("/api/confluence/crypto")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["rows"][0]["symbol"], "BTCUSDT")

    @patch("app._analysis_for", return_value=(None, "UP"))
    def test_market_cell_includes_timeframe_trend_without_signal(self, _analysis):
        result = app._cell("BTCUSDT", "1h", 100)
        self.assertEqual(result["status"], "—")
        self.assertEqual(result["trend"], "UP")


if __name__ == "__main__":
    unittest.main()
