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
BANGKOK_TZ = timezone(timedelta(hours=7))
IMPORTANT_WORDS = (
    "fed", "federal reserve", "sec", "etf", "hack", "exploit", "listing",
    "delist", "unlock", "airdrop", "mainnet", "regulation", "approval",
    "partnership", "upgrade", "launch", "cpi", "interest rate",
)


class AltFinsFeed:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached: tuple[str, list[dict]] | None = None
        self._last_updated_at = 0
        self._translations: dict[str, str] = {}
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": "FiboRetestDashboard/1.0"})
        cache_root = os.getenv("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), ".cache"
        )
        self._cache_path = os.getenv(
            "ALTFINS_CACHE_FILE",
            os.path.join(cache_root, "FiboRetestMonitor", "altfins-feed.json"),
        )

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
                "from": "last 7 days",
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

    @staticmethod
    def _refresh_hours() -> list[int]:
        try:
            hours = {
                int(value.strip())
                for value in os.getenv("ALTFINS_REFRESH_HOURS", "7,19").split(",")
                if value.strip()
            }
            valid = sorted(hour for hour in hours if 0 <= hour <= 23)
            return valid or [7, 19]
        except ValueError:
            return [7, 19]

    def _slot_key(self, now: datetime | None = None) -> str:
        local_now = now.astimezone(BANGKOK_TZ) if now else datetime.now(BANGKOK_TZ)
        hours = self._refresh_hours()
        eligible = [hour for hour in hours if hour <= local_now.hour]
        if eligible:
            slot_date = local_now.date()
            slot_hour = eligible[-1]
        else:
            slot_date = (local_now - timedelta(days=1)).date()
            slot_hour = hours[-1]
        return f"{slot_date.isoformat()}-{slot_hour:02d}"

    def _next_refresh_at(self, now: datetime | None = None) -> int:
        local_now = now.astimezone(BANGKOK_TZ) if now else datetime.now(BANGKOK_TZ)
        for hour in self._refresh_hours():
            candidate = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > local_now:
                return int(candidate.timestamp() * 1000)
        tomorrow = local_now + timedelta(days=1)
        candidate = tomorrow.replace(
            hour=self._refresh_hours()[0], minute=0, second=0, microsecond=0
        )
        return int(candidate.timestamp() * 1000)

    def _read_cache(self) -> tuple[str, list[dict], int] | None:
        try:
            with open(self._cache_path, encoding="utf-8") as cache_file:
                data = json.load(cache_file)
            if not isinstance(data.get("items"), list) or not data.get("slot"):
                return None
            return data["slot"], data["items"], int(data.get("updated_at", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _write_cache(self, slot: str, items: list[dict], updated_at: int) -> None:
        directory = os.path.dirname(self._cache_path)
        temporary = f"{self._cache_path}.tmp"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as cache_file:
                json.dump(
                    {"slot": slot, "updated_at": updated_at, "items": items},
                    cache_file,
                    ensure_ascii=False,
                )
            os.replace(temporary, self._cache_path)
        except OSError:
            try:
                os.remove(temporary)
            except OSError:
                pass

    def cache_info(self) -> dict[str, int]:
        return {
            "updated_at": self._last_updated_at,
            "next_refresh_at": self._next_refresh_at(),
        }

    def get_feed(self) -> list[dict]:
        slot = self._slot_key()
        with self._lock:
            if self._cached and self._cached[0] == slot:
                return self._cached[1]
            disk_cache = self._read_cache()
            if disk_cache and disk_cache[0] == slot:
                self._cached = (disk_cache[0], disk_cache[1])
                self._last_updated_at = disk_cache[2]
                return disk_cache[1]

            stale_items = disk_cache[1] if disk_cache else []
            stale_updated_at = disk_cache[2] if disk_cache else 0
            errors = []
            items = []
            for loader in (self._events, self._news):
                try:
                    items.extend(loader())
                except (requests.RequestException, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                    errors.append(str(exc))
            if not items and errors:
                if stale_items:
                    self._cached = (slot, stale_items)
                    self._last_updated_at = stale_updated_at
                    return stale_items
                raise RuntimeError(" | ".join(errors))
            if errors and stale_items:
                self._cached = (slot, stale_items)
                self._last_updated_at = stale_updated_at
                return stale_items
            items.sort(key=lambda item: (not item["important"], -item["score"], -item["timestamp"]))
            items = items[:15]
            updated_at = int(time.time() * 1000)
            self._cached = (slot, items)
            self._last_updated_at = updated_at
            self._write_cache(slot, items, updated_at)
            return items
