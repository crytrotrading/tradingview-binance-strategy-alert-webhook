"""altFINS MCP news/calendar client with lightweight Thai translation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import json
import os
from threading import Lock
import time

import requests


MCP_URL = "https://mcp.altfins.com/mcp"
IMPORTANT_WORDS = (
    "fed", "federal reserve", "sec", "etf", "hack", "exploit", "listing",
    "delist", "unlock", "airdrop", "mainnet", "regulation", "approval",
    "partnership", "upgrade", "launch", "cpi", "interest rate",
)


class AltFinsFeed:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached: tuple[float, list[dict]] | None = None
        self._translations: dict[str, str] = {}
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": "FiboRetestDashboard/1.0"})

    @property
    def api_key(self) -> str:
        return os.getenv("ALTFINS_API_KEY", "").strip()

    @staticmethod
    def _sse_json(response: requests.Response) -> dict:
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:])
        raise RuntimeError("altFINS ส่งข้อมูลกลับมาในรูปแบบที่อ่านไม่ได้")

    def _call_tool(self, name: str, arguments: dict) -> list[dict]:
        if not self.api_key:
            raise RuntimeError("กรุณาตั้งค่า ALTFINS_API_KEY ก่อนเปิดโปรแกรม")
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "fibo-monitor", "version": "1.0"},
            },
        }
        response = self._http.post(MCP_URL, headers=headers, json=initialize, timeout=20)
        initialized = self._sse_json(response)
        if "error" in initialized:
            raise RuntimeError(initialized["error"].get("message", "เชื่อมต่อ altFINS ไม่สำเร็จ"))
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        result = self._sse_json(
            self._http.post(MCP_URL, headers=headers, json=request, timeout=30)
        )
        if "error" in result:
            raise RuntimeError(result["error"].get("message", "altFINS query ไม่สำเร็จ"))
        tool_result = result.get("result", {})
        if tool_result.get("isError"):
            message = next(
                (item.get("text") for item in tool_result.get("content", []) if item.get("type") == "text"),
                "altFINS query ไม่สำเร็จ",
            )
            raise RuntimeError(message)
        text = next(
            (item.get("text") for item in tool_result.get("content", []) if item.get("type") == "text"),
            "[]",
        )
        data = json.loads(text)
        return data if isinstance(data, list) else []

    def _translate(self, text: str) -> str:
        clean = html.unescape(text).strip()
        translation_enabled = os.getenv(
            "ENABLE_THAI_TRANSLATION", "true"
        ).lower() in {"1", "true", "yes"}
        if not clean or not translation_enabled:
            return clean
        if clean in self._translations:
            return self._translations[clean]
        try:
            response = self._http.get(
                "https://api.mymemory.translated.net/get",
                params={"q": clean[:450], "langpair": "en|th"},
                timeout=12,
            )
            response.raise_for_status()
            translated = html.unescape(
                response.json().get("responseData", {}).get("translatedText", "")
            ).strip()
            if translated and translated.upper() != "NO QUERY SPECIFIED":
                self._translations[clean] = translated
                return translated
        except (requests.RequestException, ValueError):
            pass
        return clean

    @staticmethod
    def _symbol_from_event(item: dict) -> str:
        return (
            item.get("securityIdentifier", {})
            .get("symbol", {})
            .get("symbol", "")
        )

    def _news(self) -> list[dict]:
        items = self._call_tool(
            "news_getCryptoNewsMessages",
            {
                "from": "last 2 days",
                "to": "today",
                "page": 1,
                "size": 15,
                "sponsored": False,
            },
        )
        output = []
        for item in items:
            title = html.unescape(item.get("title", "")).strip()
            symbols = item.get("assetSymbols", "")
            score = sum(word in title.lower() for word in IMPORTANT_WORDS)
            score += sum(symbol in {"BTC", "ETH", "SOL", "XRP"} for symbol in symbols.split(", "))
            output.append(
                {
                    "id": f"news-{item.get('id')}",
                    "kind": "ข่าว",
                    "title": self._translate(title),
                    "original_title": title,
                    "symbols": symbols,
                    "timestamp": int(float(item.get("timestamp", 0))) * 1000,
                    "url": item.get("url", ""),
                    "source": item.get("newsSource", {}).get("name", "altFINS"),
                    "important": score > 0,
                    "score": score,
                }
            )
        return output

    def _events(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=30)
        items = self._call_tool(
            "getCryptoCalendarEvents",
            {
                "eventFrom": now.strftime("%Y-%m-%dT00:00:00.000"),
                "eventTo": end.strftime("%Y-%m-%dT23:59:59.999"),
                "page": 1,
                "size": 20,
            },
        )
        output = []
        for item in items:
            title = html.unescape(item.get("title", "")).strip()
            score = int(bool(item.get("significant"))) * 3
            score += int(bool(item.get("hot"))) * 2
            score += int(bool(item.get("trending")))
            output.append(
                {
                    "id": f"event-{item.get('id')}",
                    "kind": "อีเวนต์",
                    "title": self._translate(title),
                    "original_title": title,
                    "symbols": self._symbol_from_event(item),
                    "timestamp": int(float(item.get("dateEvent", 0))) * 1000,
                    "url": "",
                    "source": item.get("coinMarketCalCategories", "altFINS").replace("_", " ").title(),
                    "important": score > 0,
                    "score": score,
                }
            )
        return output

    def get_feed(self) -> list[dict]:
        ttl = max(300, int(os.getenv("ALTFINS_CACHE_SECONDS", "900")))
        now = time.monotonic()
        with self._lock:
            if self._cached and now - self._cached[0] < ttl:
                return self._cached[1]
            errors = []
            items = []
            for loader in (self._events, self._news):
                try:
                    items.extend(loader())
                except (requests.RequestException, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                    errors.append(str(exc))
            if not items and errors:
                raise RuntimeError(" | ".join(errors))
            items.sort(key=lambda item: (not item["important"], -item["score"], -item["timestamp"]))
            items = items[:15]
            self._cached = (now, items)
            return items
