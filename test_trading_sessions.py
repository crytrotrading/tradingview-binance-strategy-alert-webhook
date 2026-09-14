import unittest

from trading_sessions import sessions_for_symbol


class TradingSessionTests(unittest.TestCase):
    def test_returns_primary_and_secondary_thailand_windows(self):
        self.assertEqual(
            sessions_for_symbol("EURUSD"),
            {
                "primary": "19:00–23:00",
                "secondary": "14:00–17:00",
                "timezone": "Asia/Bangkok",
            },
        )

    def test_unknown_symbol_has_no_suggested_window(self):
        result = sessions_for_symbol("USDUS")
        self.assertIsNone(result["primary"])
        self.assertIsNone(result["secondary"])


if __name__ == "__main__":
    unittest.main()
