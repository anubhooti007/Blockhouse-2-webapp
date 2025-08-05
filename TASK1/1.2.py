#!/usr/bin/env python3
import asyncio
import aiohttp
import time
import json
import sys
import argparse
import re
from typing import Any, Dict, List, Tuple, Optional

# Import dual-source Binance helper
from binance_dual_source import binance_dual


# Helpers
def to_ms(ts: Optional[int]) -> int:
    return int(ts) if ts is not None else int(time.time() * 1000)

def sort_book(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]):
    bids.sort(key=lambda x: x[0], reverse=True)  # high -> low
    asks.sort(key=lambda x: x[0])                # low -> high

def pretty_print(book: Dict[str, Any], top: int = 10):
    ex = book["exchange"].upper()
    sym = book["symbol"]
    print(f"{ex} | symbol={sym} | ts={book['timestamp']}")
    print(f"  levels: bids={len(book['bids'])} asks={len(book['asks'])}")
    if book.get("mid") is not None:
        print(f"  Mid: {book['mid']:.2f} | Spread: {book['spread']:.2f} ({book['bps']:.2f} bps)")
    if top > 0:
        tb = book['bids'][:top]
        ta = book['asks'][:top]
        print("  Top bids:")
        for p, q in tb:
            print(f"    {p:.8f}  x {q:.8f}")
        print("  Top asks:")
        for p, q in ta:
            print(f"    {p:.8f}  x {q:.8f}")
    print("")

def mid_spread(bids, asks):
    if not bids or not asks: return None, None, None
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    spread = ba - bb
    bps = (spread / mid) * 10_000
    return mid, spread, bps



_DERIBIT_DATE = re.compile(r"^[A-Z]+-\d{2}[A-Z]{3}\d{2}$")
def is_deribit_instrument(txt: str) -> bool:
    s = txt.strip().upper()
    return s.endswith("-PERPETUAL") or bool(_DERIBIT_DATE.match(s))
def base_from_instrument(txt: str) -> str:
    return txt.strip().upper().split("-")[0]
def map_to_binance_spot(txt: str) -> str:
    return f"{base_from_instrument(txt)}USDT"
def map_to_kucoin_spot(txt: str) -> str:
    return f"{base_from_instrument(txt)}-USDT"

# ============== Simple in-memory L2 book ==============
class Book:
    __slots__ = ("bids", "asks", "timestamp")
    def __init__(self):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.timestamp: int = to_ms(None)

    def load_snapshot(self, bids: List[Tuple[float,float]], asks: List[Tuple[float,float]], ts: Optional[int]):
        self.bids = {float(p): float(q) for p, q in bids if float(q) > 0}
        self.asks = {float(p): float(q) for p, q in asks if float(q) > 0}
        self.timestamp = to_ms(ts)

    def upsert_bid(self, price: float, size: float):
        if size <= 0:
            self.bids.pop(price, None)
        else:
            self.bids[price] = size

    def upsert_ask(self, price: float, size: float):
        if size <= 0:
            self.asks.pop(price, None)
        else:
            self.asks[price] = size

    def top_sorted(self):
        bids = sorted(((p,q) for p,q in self.bids.items() if q>0), key=lambda x:x[0], reverse=True)
        asks = sorted(((p,q) for p,q in self.asks.items() if q>0), key=lambda x:x[0])
        return bids, asks

# Base connector
class L2Connector:
    name = "exchange"
    def normalize(self, pair: str) -> str:
        return pair
    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError
    async def stream_l2(self, pair: str, **kwargs):
        """Yield updated full-book snapshots (dict with bids/asks) as they change."""
        raise NotImplementedError

# Binance (REST + WS L2) with dual-source support
class BinanceL2(L2Connector):
    """
    REST: /api/v3/depth?symbol=BTCUSDT&limit=5000
    WS  : wss://stream.binance.com:9443/ws/{symbol.lower()}@depth@100ms
    Sequencing: use lastUpdateId from REST; then apply WS diffs where U <= lastUpdateId+1 <= u.
    """
    name = "binance"
    WS_GLOBAL = "wss://stream.binance.com:9443/ws"
    WS_US = "wss://stream.binance.us:9443/ws"

    def normalize(self, pair: str) -> str:
        if is_deribit_instrument(pair):
            return map_to_binance_spot(pair)
        return pair.replace("-", "").replace("_", "").replace("/", "").upper()

    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, limit: int = 5000, **_) -> Dict[str, Any]:
        symbol = self.normalize(pair)
        limit = max(1, min(int(limit), 5000))
        params = {"symbol": symbol, "limit": limit}
        
        data = await binance_dual.fetch_json(session, symbol, "/api/v3/depth", params)
        
        bids = [(float(p), float(q)) for p, q, *_ in data.get("bids", [])]
        asks = [(float(p), float(q)) for p, q, *_ in data.get("asks", [])]
        sort_book(bids, asks)
        ts = to_ms(None)  # API doesn't return ts
        mid, spread, bps = mid_spread(bids, asks)
        return {"exchange": self.name, "symbol": symbol, "timestamp": ts,
                "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps,
                "raw": {"lastUpdateId": data.get("lastUpdateId")}}

    async def stream_l2(self, pair: str, limit: int = 1000, top: int = 10):
        symbol = self.normalize(pair)
        
        # 1) REST snapshot with dual-source
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent":"l2-ws/1.0"}) as sess:
            snap = await self.fetch_l2(sess, symbol, limit=min(limit, 5000))
            book = Book()
            book.load_snapshot(snap["bids"], snap["asks"], snap["timestamp"])
            last_id = snap["raw"]["lastUpdateId"]
            
            # Determine WebSocket endpoints based on symbol availability
            await binance_dual.initialize_cache(sess)
        
        # 2) WS diffs with dual-source endpoints
        stream = f"{symbol.lower()}@depth@100ms"
        ws_urls = []
        if symbol in binance_dual.global_spot_symbols:
            ws_urls.append(f"{self.WS_GLOBAL}/{stream}")
        if symbol in binance_dual.us_spot_symbols:
            ws_urls.append(f"{self.WS_US}/{stream}")
        
        if not ws_urls:
            # Symbol not in cache, try both
            ws_urls = [f"{self.WS_GLOBAL}/{stream}", f"{self.WS_US}/{stream}"]
        
        backoff = 1.0
        url_idx = 0
        
        while True:
            url = ws_urls[url_idx % len(ws_urls)]
            source = "binance.com" if "binance.com" in url else "binance.us"
            
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=20) as ws:
                        print(f"[WS:BINANCE] {symbol}: L2 stream connected to {source}")
                        while True:
                            msg = await ws.receive(timeout=25)
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            data = json.loads(msg.data)
                            if "b" not in data or "a" not in data:
                                continue
                            U, u = data.get("U"), data.get("u")
                            # apply only when U <= last_id+1 <= u
                            if U is None or u is None:
                                continue
                            if u < last_id + 1:
                                # too old
                                continue
                            if U <= last_id + 1 <= u:
                                # apply
                                for p, q in data["b"]:
                                    book.upsert_bid(float(p), float(q))
                                for p, q in data["a"]:
                                    book.upsert_ask(float(p), float(q))
                                last_id = u
                                bids, asks = book.top_sorted()
                                mid, spread, bps = mid_spread(bids, asks)
                                yield {"exchange": self.name, "symbol": symbol, "timestamp": to_ms(None),
                                       "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}
                            else:
                                # gap detected -> resync
                                print(f"[WS:BINANCE] {symbol}: Gap detected, resyncing snapshot via dual-source...")
                                async with aiohttp.ClientSession(timeout=timeout) as s2:
                                    snap = await self.fetch_l2(s2, symbol, limit=min(limit, 5000))
                                book.load_snapshot(snap["bids"], snap["asks"], snap["timestamp"])
                                last_id = snap["raw"]["lastUpdateId"]
                                bids, asks = book.top_sorted()
                                mid, spread, bps = mid_spread(bids, asks)
                                yield {"exchange": self.name, "symbol": symbol, "timestamp": to_ms(None),
                                       "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}
                backoff = 1.0
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                print(f"[WS:BINANCE] {symbol}: {source} failed ({type(e).__name__}: {e}). Reconnecting in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff*2, 30.0)
                # Try next URL on reconnection
                url_idx += 1

# KuCoin (REST + WS L2)
class KucoinL2(L2Connector):
    """
    REST (public): /api/v1/market/orderbook/level2_100 (no auth)
    REST (full v3 requires auth; omitted here)
    WS: topic '/market/level2:{symbol}'
    Sequencing: use snapshot 'sequence', then accept msgs with sequenceStart <= seq+1 <= sequenceEnd.
    """
    name = "kucoin"
    REST = "https://api.kucoin.com"
    BULLET = "/api/v1/bullet-public"

    def normalize(self, pair: str) -> str:
        if is_deribit_instrument(pair):
            return map_to_kucoin_spot(pair)
        s = pair.replace("_", "-").replace("/", "-").upper()
        if "-" not in s:
            for q in ("USDT","USDC","BTC","ETH","USD"):
                if s.endswith(q) and len(s)>len(q):
                    s = f"{s[:-len(q)]}-{q}"
                    break
        return s

    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, **_) -> Dict[str, Any]:
        symbol = self.normalize(pair)
        url = f"{self.REST}/api/v1/market/orderbook/level2_100"
        async with session.get(url, params={"symbol": symbol}) as r:
            text = await r.text()
            if r.status != 200:
                raise RuntimeError(f"KuCoin HTTP {r.status}: {text[:300]}")
            data = json.loads(text)
        if data.get("code") != "200000":
            raise RuntimeError(f"KuCoin error: {data}")
        d = data.get("data") or {}
        bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
        sort_book(bids, asks)
        ts = int(d.get("time") or time.time()*1000)
        mid, spread, bps = mid_spread(bids, asks)
        return {"exchange": self.name, "symbol": symbol, "timestamp": ts,
                "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps,
                "raw": {"sequence": int(d.get("sequence", 0))}}

    async def _get_ws_info(self) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{self.REST}{self.BULLET}") as r:
                data = await r.json()
        if data.get("code") != "200000":
            raise RuntimeError(f"KuCoin bullet-public error: {data}")
        d = data["data"]
        server = d["instanceServers"][0]
        return {
            "endpoint": server["endpoint"],
            "token": d["token"],
            "pingInterval": server.get("pingInterval", 20000)
        }

    async def stream_l2(self, pair: str, top: int = 10):
        symbol = self.normalize(pair)
        # 1) Snapshot
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent":"l2-ws/1.0"}) as sess:
            snap = await self.fetch_l2(sess, symbol)
            book = Book()
            book.load_snapshot(snap["bids"], snap["asks"], snap["timestamp"])
            seq = snap["raw"]["sequence"]

        # 2) WS subscribe
        info = await self._get_ws_info()
        url = f"{info['endpoint']}?token={info['token']}&connectId={int(time.time()*1000)}"
        topic = f"/market/level2:{symbol}"
        backoff = 1.0

        def _apply_changes(changes, is_bid):
            for p, sz, *_ in changes:
                price = float(p); size = float(sz)
                (book.upsert_bid if is_bid else book.upsert_ask)(price, size)

        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=None) as ws:
                        # subscribe
                        await ws.send_json({"id": str(int(time.time()*1000)), "type": "subscribe",
                                            "topic": topic, "privateChannel": False, "response": True})
                        # ping task
                        async def pinger():
                            while True:
                                await asyncio.sleep(info["pingInterval"]/1000.0)
                                try:
                                    await ws.send_json({"id": str(int(time.time()*1000)), "type": "ping"})
                                except Exception:
                                    break
                        pt = asyncio.create_task(pinger())

                        while True:
                            msg = await ws.receive(timeout=30)
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            data = json.loads(msg.data)
                            if data.get("type") == "pong": continue
                            if data.get("type") != "message" or data.get("topic") != topic:
                                continue
                            d = data.get("data") or {}
                            s_start = d.get("sequenceStart"); s_end = d.get("sequenceEnd")
                            if s_start is None or s_end is None:  # heartbeat/other
                                continue
                            # sequencing check
                            if s_start <= seq + 1 <= s_end:
                                ch = d.get("changes") or {}
                                _apply_changes(ch.get("bids", []), True)
                                _apply_changes(ch.get("asks", []), False)
                                seq = s_end
                                book.timestamp = int(d.get("time") or time.time()*1000)
                                bids, asks = book.top_sorted()
                                mid, spread, bps = mid_spread(bids, asks)
                                yield {"exchange": self.name, "symbol": symbol, "timestamp": book.timestamp,
                                       "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}
                            elif s_end < seq + 1:
                                # old message, ignore
                                continue
                            else:
                                # gap -> resnapshot
                                print("[WS:KUCOIN] Gap detected, resnapshot…")
                                async with aiohttp.ClientSession(timeout=timeout) as s2:
                                    snap = await self.fetch_l2(s2, symbol)
                                book.load_snapshot(snap["bids"], snap["asks"], snap["timestamp"])
                                seq = snap["raw"]["sequence"]
                                bids, asks = book.top_sorted()
                                mid, spread, bps = mid_spread(bids, asks)
                                yield {"exchange": self.name, "symbol": symbol, "timestamp": book.timestamp,
                                       "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}
                        pt.cancel()
                backoff = 1.0
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                print(f"[WS:KUCOIN] {type(e).__name__}: {e} (reconnecting in {backoff:.0f}s)")
                await asyncio.sleep(backoff); backoff = min(backoff*2, 30.0)

# Bybit (REST + WS L2)
class BybitL2(L2Connector):
    """
    REST: /v5/market/orderbook?category=spot|linear|inverse&symbol=...&limit=...
    WS  : wss://stream.bybit.com/v5/public/{category}
          subscribe args: ["orderbook.50.SYMBOL"] or "orderbook.200.SYMBOL"
    Messages: type=snapshot|delta
    """
    name = "bybit"
    REST = "https://api.bybit.com"
    WS_BASE = "wss://stream.bybit.com/v5/public"

    def normalize(self, pair: str) -> str:
        if is_deribit_instrument(pair):
            return map_to_binance_spot(pair)  # BTCUSDT
        return pair.replace("-", "").replace("_", "").replace("/", "").upper()

    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, category: str = "spot", limit: int = 200, **_) -> Dict[str, Any]:
        symbol = self.normalize(pair)
        if is_deribit_instrument(pair) and category == "spot":
            category = "linear"
        max_limit = 200 if category == "spot" else 500
        limit = max(1, min(int(limit), max_limit))
        url = f"{self.REST}/v5/market/orderbook"
        params = {"category": category, "symbol": symbol, "limit": limit}
        async with session.get(url, params=params) as r:
            text = await r.text()
            if r.status != 200:
                raise RuntimeError(f"Bybit HTTP {r.status}: {text[:300]}")
            data = json.loads(text)
        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit error: {data}")
        res = data.get("result") or {}
        bids = [(float(p), float(q)) for p, q in res.get("b", [])]
        asks = [(float(p), float(q)) for p, q in res.get("a", [])]
        sort_book(bids, asks)
        ts = to_ms(res.get("ts"))
        mid, spread, bps = mid_spread(bids, asks)
        return {"exchange": self.name, "symbol": symbol, "timestamp": ts,
                "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps,
                "raw": {"category": category, "limit": limit}}

    async def stream_l2(self, pair: str, category: str = "spot", limit: int = 50, top: int = 10):
        symbol = self.normalize(pair)
        if is_deribit_instrument(pair) and category == "spot":
            category = "linear"
        # snapshot
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent":"l2-ws/1.0"}) as sess:
            snap = await self.fetch_l2(sess, symbol, category=category, limit=limit)
            book = Book()
            book.load_snapshot(snap["bids"], snap["asks"], snap["timestamp"])

        # ws
        depth_tag = "200" if (category != "spot" and limit and limit > 50) else "50"
        topic = f"orderbook.{depth_tag}.{symbol}"
        url = f"{self.WS_BASE}/{category}"
        sub = {"op": "subscribe", "args": [topic]}
        backoff = 1.0
        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=20) as ws:
                        await ws.send_json(sub)
                        print(f"[WS:BYBIT] {category} {topic} subscribed")
                        while True:
                            msg = await ws.receive(timeout=25)
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            data = json.loads(msg.data)
                            if data.get("topic") != topic or "type" not in data:
                                continue
                            tp = data["type"]
                            d = data.get("data") or {}
                            if tp == "snapshot":
                                bids = [(float(p), float(q)) for p, q in d.get("b", [])]
                                asks = [(float(p), float(q)) for p, q in d.get("a", [])]
                                book.load_snapshot(bids, asks, to_ms(d.get("ts")))
                            elif tp == "delta":
                                for p, q in d.get("b", []):
                                    book.upsert_bid(float(p), float(q))
                                for p, q in d.get("a", []):
                                    book.upsert_ask(float(p), float(q))
                                book.timestamp = to_ms(d.get("ts"))
                            else:
                                continue
                            bids, asks = book.top_sorted()
                            mid, spread, bps = mid_spread(bids, asks)
                            yield {"exchange": self.name, "symbol": symbol, "timestamp": book.timestamp,
                                   "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}
                backoff = 1.0
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                print(f"[WS:BYBIT] {type(e).__name__}: {e} (reconnecting in {backoff:.0f}s)")
                await asyncio.sleep(backoff); backoff = min(backoff*2, 30.0)

# Deribit (REST + WS L2)
class DeribitL2(L2Connector):
    """
    REST: /api/v2/public/get_order_book?instrument_name=BTC-PERPETUAL&depth=50
    WS  : channel "book.{instrument}.100ms"
    WS payload: type=snapshot|change, with bids/asks entries as [price, amount] or {"price","amount"}
    """
    name = "deribit"
    REST = "https://www.deribit.com/api/v2"
    WS   = "wss://www.deribit.com/ws/api/v2"

    def normalize(self, pair: str) -> str:
        s = pair.strip().upper().replace("_", "-")
        # If already a Deribit instrument, return as-is
        if "-PERPETUAL" in s or ("-" in s and len(s.split("-")) > 2):
            return s
        # Convert any token to perpetual format
        if "USDT" in s or "USD" in s or "/" in s or "_" in s:
            base = s.replace("/", "-").replace("_", "-").replace("USDT", "").replace("USD", "").split("-")[0]
            perp = f"{base}-PERPETUAL"
            print(f"[DERIBIT] Converting {pair} -> {perp}")
            return perp
        # Single token (e.g., "BTC", "ETH") -> BTC-PERPETUAL
        if s.isalpha():
            perp = f"{s}-PERPETUAL"
            print(f"[DERIBIT] Converting {pair} -> {perp}")
            return perp
        return s

    @staticmethod
    def _parse_side(side):
        if not side: return []
        first = side[0]
        if isinstance(first, dict):
            return [(float(x["price"]), float(x["amount"]))
                    for x in side if "price" in x and "amount" in x]
        out = []
        for x in side:
            if isinstance(x, (list, tuple)) and len(x) >= 2:
                try: out.append((float(x[0]), float(x[1])))
                except: pass
        return out

    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, limit: int = 50, **_) -> Dict[str, Any]:
        instrument = self.normalize(pair)
        depth = max(1, int(limit))
        url = f"{self.REST}/public/get_order_book"
        params = {"instrument_name": instrument, "depth": depth}
        async with session.get(url, params=params) as r:
            text = await r.text()
            if r.status != 200:
                raise RuntimeError(f"Deribit HTTP {r.status}: {text[:300]}")
            data = json.loads(text)
        result = data.get("result") or {}
        bids = self._parse_side(result.get("bids"))
        asks = self._parse_side(result.get("asks"))
        sort_book(bids, asks)
        ts = result.get("timestamp")
        mid, spread, bps = mid_spread(bids, asks)
        return {"exchange": self.name, "symbol": instrument, "timestamp": to_ms(ts),
                "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}

    async def stream_l2(self, pair: str, limit: int = 50, top: int = 10, testnet: bool = False, 
                        idle_resnapshot_sec: int = 5):
        instrument = self.normalize(pair)
        if testnet:
            self.REST = "https://test.deribit.com/api/v2"
            self.WS   = "wss://test.deribit.com/ws/api/v2"

        backoff = 1.0
        # Try raw first (more active but needs auth), fall back to 100ms (public)
        channels_to_try = [f"book.{instrument}.raw", f"book.{instrument}.100ms"]
        current_channel_idx = 0
        
        while True:
            try:
                # Initial REST snapshot
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent":"l2-ws/1.0"}) as sess:
                    snap = await self.fetch_l2(sess, instrument, limit=limit)
                    book = Book()
                    book.load_snapshot(snap["bids"], snap["asks"], snap["timestamp"])

                last_update = time.time()
                # yield initial view
                bids, asks = book.top_sorted()
                mid, spread, bps = mid_spread(bids, asks)
                yield {"exchange": self.name, "symbol": instrument, "timestamp": book.timestamp,
                       "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}

                # WS subscribe - try current channel
                channel = channels_to_try[current_channel_idx]
                sub = {"jsonrpc": "2.0", "id": 1, "method": "public/subscribe",
                       "params": {"channels": [channel]}}

                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(self.WS, heartbeat=20) as ws:
                        # heartbeat
                        await ws.send_json({"jsonrpc":"2.0","id":99,"method":"public/set_heartbeat",
                                            "params":{"interval":10}})
                        await ws.send_json(sub)
                        print(f"[WS:DERIBIT] subscribed to {channel}")

                        # queue to forward watchdog emissions into the same generator
                        queue: asyncio.Queue = asyncio.Queue()

                        async def watchdog():
                            # If we get no updates for idle_resnapshot_sec, re-fetch once
                            nonlocal last_update, book
                            while True:
                                await asyncio.sleep(1.0)
                                if time.time() - last_update >= idle_resnapshot_sec:
                                    try:
                                        async with aiohttp.ClientSession(timeout=timeout) as s2:
                                            snap2 = await self.fetch_l2(s2, instrument, limit=limit)
                                        book.load_snapshot(snap2["bids"], snap2["asks"], snap2["timestamp"])
                                        last_update = time.time()
                                        b, a = book.top_sorted()
                                        if b and a:
                                            m, sp, pb = mid_spread(b, a)
                                            yield_dict = {"exchange": self.name, "symbol": instrument,
                                                          "timestamp": book.timestamp,
                                                          "bids": b, "asks": a, "mid": m, "spread": sp, "bps": pb}
                                            # use ws loop context to emit via queue
                                            queue.put_nowait(yield_dict)
                                    except Exception:
                                        pass

                        wd_task = asyncio.create_task(watchdog())

                        async def _drain_queue_and_yield():
                            while not queue.empty():
                                yield_dict = queue.get_nowait()
                                # bubble the watchdog snapshot to the caller
                                yield yield_dict

                        while True:
                            # prefer WS, but also drain the watchdog queue
                            try:
                                msg = await ws.receive(timeout=0.5)
                            except asyncio.TimeoutError:
                                # also drain anything the watchdog enqueued
                                async for y in _drain_queue_and_yield():
                                    yield y
                                continue

                            if msg.type != aiohttp.WSMsgType.TEXT:
                                # drain and continue
                                async for y in _drain_queue_and_yield():
                                    yield y
                                continue
                            try:
                                data = json.loads(msg.data)
                            except Exception:
                                async for y in _drain_queue_and_yield():
                                    yield y
                                continue

                            # heartbeats
                            if data.get("method") == "heartbeat":
                                if data.get("params",{}).get("type") == "test_request":
                                    await ws.send_json({"jsonrpc":"2.0","id":100,"method":"public/test","params":{}})
                                # drain and continue
                                async for y in _drain_queue_and_yield():
                                    yield y
                                continue

                            if data.get("method") != "subscription":
                                # Check for auth error on raw channel
                                if (data.get("error", {}).get("code") == 13778 and 
                                    current_channel_idx == 0 and len(channels_to_try) > 1):
                                    print(f"[WS:DERIBIT] Raw channel needs auth, switching to {channels_to_try[1]}")
                                    current_channel_idx = 1
                                    # Break out to reconnect with new channel
                                    break
                                # drain and continue
                                async for y in _drain_queue_and_yield():
                                    yield y
                                continue
                            params = data.get("params") or {}
                            if params.get("channel") != channel:
                                continue

                            d = params.get("data") or {}
                            tp = d.get("type")

                            if tp == "snapshot":
                                bids_rows = self._parse_side(d.get("bids") or [])
                                asks_rows = self._parse_side(d.get("asks") or [])
                                if not bids_rows and not asks_rows:
                                    # sometimes Deribit sends an empty snapshot right after sub
                                    continue
                                book.load_snapshot(bids_rows, asks_rows, d.get("timestamp"))
                                last_update = time.time()

                            elif tp == "change":
                                bid_changes = self._parse_side(d.get("bids") or [])
                                ask_changes = self._parse_side(d.get("asks") or [])
                                if not bid_changes and not ask_changes:
                                    continue
                                for p, q in bid_changes:
                                    book.upsert_bid(p, q)
                                for p, q in ask_changes:
                                    book.upsert_ask(p, q)
                                book.timestamp = to_ms(d.get("timestamp"))
                                last_update = time.time()

                            else:
                                continue

                            b, a = book.top_sorted()
                            if not b or not a:
                                continue
                            m, sp, pb = mid_spread(b, a)
                            yield {"exchange": self.name, "symbol": instrument, "timestamp": book.timestamp,
                                   "bids": b, "asks": a, "mid": m, "spread": sp, "bps": pb}

                            # After you yield a normal book update, also drain any extra snapshots
                            async for y in _drain_queue_and_yield():
                                yield y

                        wd_task.cancel()

                backoff = 1.0
            except Exception as e:
                print(f"[WS:DERIBIT] {type(e).__name__}: {e} (reconnecting in {backoff:.0f}s)")
                await asyncio.sleep(backoff)
                backoff = min(backoff*2, 30.0)

# BitMart (REST + WS L2)
class BitmartL2(L2Connector):
    """BitMart L2 order book connector"""
    name = "bitmart"
    REST = "https://api-cloud.bitmart.com"
    WS = "wss://ws-manager-compress.bitmart.com/api?protocol=1.1"

    def normalize(self, pair: str) -> str:
        s = pair.replace("-", "_").replace("/", "_").upper()
        if "_" not in s:
            for q in ("USDT", "USDC", "BTC", "ETH", "USD"):
                if s.endswith(q) and len(s) > len(q):
                    s = f"{s[:-len(q)]}_{q}"
                    break
        return s

    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, limit: int = 50, **_) -> Dict[str, Any]:
        symbol = self.normalize(pair)
        url = f"{self.REST}/spot/quotation/v3/books"
        params = {"symbol": symbol, "limit": min(limit, 50)}
        async with session.get(url, params=params) as r:
            if r.status != 200:
                raise RuntimeError(f"BitMart HTTP {r.status}: {await r.text()}")
            data = await r.json()
        
        if data.get("code") != 1000:
            raise RuntimeError(f"BitMart error: {data}")
        
        d = data.get("data", {})
        bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
        sort_book(bids, asks)
        
        ts = int(d.get("ts", time.time() * 1000))
        mid, spread, bps = mid_spread(bids, asks)
        
        return {"exchange": self.name, "symbol": symbol, "timestamp": ts,
                "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}

    async def stream_l2(self, pair: str, limit: int = 50, top: int = 10):
        symbol = self.normalize(pair)
        # BitMart WebSocket L2 implementation would go here
        # For now, use polling fallback
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    book = await self.fetch_l2(sess, symbol, limit=limit)
                    yield book
                await asyncio.sleep(1)  # 1-second polling
            except Exception as e:
                print(f"[WS:BITMART] {e} (retrying in 5s)")
                await asyncio.sleep(5)

# OKX (REST + WS L2)
class OkxL2(L2Connector):
    """OKX L2 order book connector"""
    name = "okx"
    REST = "https://www.okx.com"
    WS = "wss://ws.okx.com:8443/ws/v5/public"

    def normalize(self, pair: str) -> str:
        s = pair.replace("_", "-").replace("/", "-").upper()
        if "-" not in s:
            for q in ("USDT", "USDC", "BTC", "ETH", "USD"):
                if s.endswith(q) and len(s) > len(q):
                    s = f"{s[:-len(q)]}-{q}"
                    break
        return s

    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, limit: int = 400, **_) -> Dict[str, Any]:
        symbol = self.normalize(pair)
        url = f"{self.REST}/api/v5/market/books"
        params = {"instId": symbol, "sz": min(limit, 400)}
        
        # Disable SSL for geo-blocking issues
        connector = aiohttp.TCPConnector(ssl=False)
        headers = {"User-Agent": "l2-orderbook/1.0", "Accept": "application/json"}
        
        async with aiohttp.ClientSession(connector=connector, headers=headers) as sess:
            async with sess.get(url, params=params) as r:
                if r.status == 403:
                    raise RuntimeError("OKX geo-blocked. Use VPN or VM.")
                if r.status != 200:
                    raise RuntimeError(f"OKX HTTP {r.status}: {await r.text()}")
                data = await r.json()
        
        if data.get("code") != "0":
            raise RuntimeError(f"OKX error: {data}")
        
        d = data["data"][0]
        bids = [(float(p), float(q)) for p, q, *_ in d.get("bids", [])]
        asks = [(float(p), float(q)) for p, q, *_ in d.get("asks", [])]
        sort_book(bids, asks)
        
        ts = int(d.get("ts", time.time() * 1000))
        mid, spread, bps = mid_spread(bids, asks)
        
        return {"exchange": self.name, "symbol": symbol, "timestamp": ts,
                "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}

    async def stream_l2(self, pair: str, limit: int = 50, top: int = 10):
        symbol = self.normalize(pair)
        # OKX WebSocket L2 implementation with geo-blocking handling
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    book = await self.fetch_l2(sess, symbol, limit=limit)
                    yield book
                await asyncio.sleep(1)  # 1-second polling
            except Exception as e:
                print(f"[WS:OKX] {e} (retrying in 5s)")
                await asyncio.sleep(5)


# Hyperliquid (REST + WS L2)
class HyperliquidL2(L2Connector):
    """Hyperliquid L2 order book connector"""
    name = "hyperliquid"
    REST = "https://api.hyperliquid.xyz"
    WS = "wss://api.hyperliquid.xyz/ws"

    def normalize(self, pair: str) -> str:
        s = pair.upper().replace("-", "").replace("_", "").replace("/", "")
        for quote in ("USDT", "USDC", "USD", "PERP", "PERPETUAL"):
            if s.endswith(quote):
                s = s[:-len(quote)]
                break
        return s

    async def fetch_l2(self, session: aiohttp.ClientSession, pair: str, limit: int = 50, **_) -> Dict[str, Any]:
        coin = self.normalize(pair)
        url = f"{self.REST}/info"
        payload = {"type": "l2Book", "coin": coin}
        
        async with session.post(url, json=payload) as r:
            if r.status != 200:
                raise RuntimeError(f"Hyperliquid HTTP {r.status}: {await r.text()}")
            data = await r.json()
        
        if not data or "levels" not in data:
            raise RuntimeError(f"Hyperliquid error: {data}")
        
        levels = data["levels"]
        if isinstance(levels, dict):
            bid_data = levels.get("bids", [])
            ask_data = levels.get("asks", [])
        elif isinstance(levels, list) and len(levels) >= 2:
            bid_data = levels[0] or []
            ask_data = levels[1] or []
        else:
            raise RuntimeError(f"Unexpected levels format: {levels}")
        
        # Parse bids/asks (can be dict or list format)
        bids = []
        asks = []
        
        for item in bid_data[:limit]:
            if isinstance(item, dict):
                bids.append((float(item["px"]), float(item["sz"])))
            elif isinstance(item, list) and len(item) >= 2:
                bids.append((float(item[0]), float(item[1])))
        
        for item in ask_data[:limit]:
            if isinstance(item, dict):
                asks.append((float(item["px"]), float(item["sz"])))
            elif isinstance(item, list) and len(item) >= 2:
                asks.append((float(item[0]), float(item[1])))
        
        sort_book(bids, asks)
        ts = int(time.time() * 1000)
        mid, spread, bps = mid_spread(bids, asks)
        
        return {"exchange": self.name, "symbol": coin, "timestamp": ts,
                "bids": bids, "asks": asks, "mid": mid, "spread": spread, "bps": bps}

    async def stream_l2(self, pair: str, limit: int = 50, top: int = 10):
        coin = self.normalize(pair)
        # Hyperliquid WebSocket L2 implementation
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    book = await self.fetch_l2(sess, coin, limit=limit)
                    yield book
                await asyncio.sleep(1)  # 1-second polling
            except Exception as e:
                print(f"[WS:HYPERLIQUID] {e} (retrying in 5s)")
                await asyncio.sleep(5)

# Runner (REST + WS)
CONNECTORS = {
    "binance": BinanceL2(),
    "kucoin":  KucoinL2(),
    "bybit":   BybitL2(),
    "deribit": DeribitL2(),
    "bitmart": BitmartL2(),
    "okx": OkxL2(),
    "hyperliquid": HyperliquidL2(),
}

async def fetch_one(conn_name: str, pair: str, **kwargs) -> Dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=8)
    headers = {"User-Agent": "l2-orderbook/1.0", "Accept": "application/json"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        return await CONNECTORS[conn_name].fetch_l2(session, pair, **kwargs)

async def stream_one(conn_name: str, pair: str, **kwargs):
    async for book in CONNECTORS[conn_name].stream_l2(pair, **kwargs):
        pretty_print(book, top=kwargs.get("top", 10))



async def main():
    ap = argparse.ArgumentParser(description="L2 Order Book (snapshot/WS) – All 7 Exchanges")
    ap.add_argument("pair", help="Trading pair or instrument, e.g., BTC-USDT (spot) or BTC-PERPETUAL (Deribit)")
    ap.add_argument("--exch", choices=list(CONNECTORS.keys()) + ["all"], default="all",
                   help="Exchange to query (binance, kucoin, bybit, deribit, bitmart, okx, hyperliquid, all)")
    ap.add_argument("--limit", type=int, default=None, help="Order book depth limit")
    ap.add_argument("--category", default="spot", help="Bybit: spot|linear|inverse|option (auto 'linear' for Deribit-like input)")
    ap.add_argument("--top", type=int, default=10, help="Print only top N levels (0 = none)")
    ap.add_argument("--out", default=None, help="Write JSON to file (REST only)")
    ap.add_argument("--ws", action="store_true", help="Use WebSocket streaming instead of REST snapshot")
    args = ap.parse_args()

    targets = [args.exch] if args.exch != "all" else list(CONNECTORS.keys())

    if args.ws:
        # WebSocket streaming mode
        tasks = []
        for name in targets:
            kw = {"top": args.top}
            if name == "bybit":
                kw["category"] = ("linear" if is_deribit_instrument(args.pair) and args.category=="spot"
                                  else args.category)
                kw["limit"] = args.limit or 50
            elif name == "binance":
                kw["limit"] = args.limit or 1000
            elif name == "deribit":
                kw["limit"] = args.limit or 50
            elif name in ["bitmart", "okx", "hyperliquid"]:
                kw["limit"] = args.limit or 50
            tasks.append(asyncio.create_task(stream_one(name, args.pair, **kw)))
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        return

    # REST snapshot mode
    tasks = []
    for name in targets:
        kw = {}
        if name == "bybit":
            kw["category"] = args.category
            if args.limit: kw["limit"] = args.limit
        elif name == "binance" and args.limit: 
            kw["limit"] = args.limit
        elif name == "deribit" and args.limit: 
            kw["limit"] = args.limit
        elif name in ["bitmart", "okx", "hyperliquid"] and args.limit:
            kw["limit"] = args.limit
        tasks.append(fetch_one(name, args.pair, **kw))

    books = await asyncio.gather(*tasks, return_exceptions=True)

    out_list: List[Dict[str, Any]] = []
    for name, res in zip(targets, books):
        if isinstance(res, Exception):
            print(f"[ERROR] {name}: {res}", file=sys.stderr)
            continue
        pretty_print(res, top=args.top)
        out_list.append(res)

    if args.out and out_list:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out_list if len(out_list) > 1 else out_list[0], f, ensure_ascii=False, indent=2)
        print(f"Saved JSON to {args.out}")

if __name__ == "__main__":
    asyncio.run(main())
