import unittest
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


if __name__ == "__main__":
    unittest.main()
