import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
