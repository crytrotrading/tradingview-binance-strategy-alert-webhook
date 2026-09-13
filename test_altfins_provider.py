from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from altfins_provider import AltFinsFeed


class FakeResponse:
    headers = {"content-type": "text/event-stream"}
    text = 'event:message\ndata:{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'

    def raise_for_status(self):
        return None


class AltFinsFeedTests(unittest.TestCase):
    def test_parses_streamable_http_response(self):
        result = AltFinsFeed._sse_json(FakeResponse())
        self.assertTrue(result["result"]["ok"])

    def test_requires_key_without_exposing_it(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ALTFINS_API_KEY"):
                AltFinsFeed()._call_tool("anything", {})

    def test_extracts_event_symbol(self):
        item = {
            "securityIdentifier": {
                "symbol": {"symbol": "BTC"},
            }
        }
        self.assertEqual(AltFinsFeed._symbol_from_event(item), "BTC")

    def test_uses_two_daily_thailand_refresh_slots(self):
        feed = AltFinsFeed()
        bangkok = timezone(timedelta(hours=7))
        morning = datetime(2026, 9, 13, 10, 0, tzinfo=bangkok)
        afternoon = datetime(2026, 9, 13, 18, 59, tzinfo=bangkok)
        evening = datetime(2026, 9, 13, 20, 0, tzinfo=bangkok)
        self.assertEqual(feed._slot_key(morning), "2026-09-13-07")
        self.assertEqual(feed._slot_key(afternoon), "2026-09-13-07")
        self.assertEqual(feed._slot_key(evening), "2026-09-13-19")

    def test_persistent_cache_prevents_repeat_api_calls(self):
        item = {
            "id": "news-1",
            "important": True,
            "score": 1,
            "timestamp": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "feed.json")
            with patch.dict(os.environ, {"ALTFINS_CACHE_FILE": path}):
                feed = AltFinsFeed()
                feed._events = Mock(return_value=[])
                feed._news = Mock(return_value=[item])
                self.assertEqual(feed.get_feed(), [item])
                self.assertEqual(feed.get_feed(), [item])
                feed._events.assert_called_once()
                feed._news.assert_called_once()

                restarted = AltFinsFeed()
                restarted._events = Mock(side_effect=AssertionError("API called"))
                restarted._news = Mock(side_effect=AssertionError("API called"))
                self.assertEqual(restarted.get_feed(), [item])


if __name__ == "__main__":
    unittest.main()
