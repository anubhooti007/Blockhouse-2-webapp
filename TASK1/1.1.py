#!/usr/bin/env python3

import asyncio
import aiohttp
import time
import sys
import json
import argparse
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    ZoneInfo = None

# Import dual-source Binance helper
from binance_dual_source import binance_dual

# time utilities
def ms_to_pretty(ts_ms: int) -> Dict[str, str]:
    ts_s = ts_ms / 1000.0
    dt_utc = datetime.fromtimestamp(ts_s, tz=timezone.utc)
    iso_utc = dt_utc.isoformat()

    if ZoneInfo is not None:
        ist = ZoneInfo("Asia/Kolkata")
        iso_ist = dt_utc.astimezone(ist).isoformat()
    else:
        iso_ist = "(install Python 3.9+ for IST tz)"
    ago_s = max(0, int(time.time() - ts_s))
    if ago_s < 60:
        ago = f"{ago_s}s ago"
    elif ago_s < 3600:
        ago = f"{ago_s//60}m {ago_s%60}s ago"
    else:
        h, r = divmod(ago_s, 3600)
        m, s = divmod(r, 60)
        ago = f"{h}h {m}m {s}s ago"
    return {"utc": iso_utc, "ist": iso_ist, "ago": ago}



# Base connector
class ExchangeConnector:
    name: str = "exchange"
    async def get_best_bid_ask(self, pair_or_instr: str) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses implement this")
    def normalize_symbol(self, pair_or_instr: str) -> str:
        raise NotImplementedError("Subclasses implement this")
    async def stream_book_ticker(self, pair_or_instr: str):
        """Yield dicts with bid, ask, ts (ms) as they arrive."""
        raise NotImplementedError("Subclasses implement this")



# BitMart (REST + WS)
class BitmartConnector(ExchangeConnector):
    name = "bitmart"
    REST_BASE = "https://api-cloud.bitmart.com"
    WS_PUBLIC = "wss://ws-manager-compress.bitmart.com/api?protocol=1.1"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, timeout_s: float = 3.0):
        self._session = session
        self._own_session = False
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {"User-Agent": "bba/1.0"}

    def normalize_symbol(self, pair: str) -> str:
        s = pair.replace("-", "_").replace("/", "_").upper()
        if "_" not in s:
            for q in ("USDT", "USDC", "BTC", "ETH", "USD"):
                if s.endswith(q) and len(s) > len(q):
                    s = f"{s[:-len(q)]}_{q}"
                    break
        return s

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers, timeout=self._timeout)
            self._own_session = True

    async def _get_json(self, url: str, params: dict) -> dict:
        async with self._session.get(url, params=params) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"[BitMart] HTTP {resp.status}: {text[:300]}")
            try:
                return await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                return json.loads(text)

    async def _fetch_ticker_v3(self, symbol: str) -> Optional[Dict[str, Any]]:
        url = f"{self.REST_BASE}/spot/quotation/v3/ticker"
        data = await self._get_json(url, {"symbol": symbol})
        if data.get("code") != 1000 or "data" not in data:
            return None
        d = data["data"]
        bp, ap, ts = d.get("bid_px"), d.get("ask_px"), d.get("ts")
        if bp is None or ap is None:
            return None
        return {"bid": float(bp), "ask": float(ap), "timestamp": int(ts) if ts else int(time.time()*1000), "raw": d}

    async def _fetch_books_top1(self, symbol: str) -> Dict[str, Any]:
        url = f"{self.REST_BASE}/spot/quotation/v3/books"
        data = await self._get_json(url, {"symbol": symbol, "limit": 1})
        if data.get("code") != 1000 or "data" not in data:
            raise RuntimeError(f"[BitMart] Unexpected books response: {data}")
        d = data["data"]
        bids, asks = d.get("bids") or [], d.get("asks") or []
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        ts_ms = int(d.get("ts", int(time.time()*1000)))
        return {"bid": best_bid, "ask": best_ask, "timestamp": ts_ms, "raw": d}

    async def get_best_bid_ask(self, pair: str) -> Dict[str, Any]:
        await self._ensure_session()
        symbol = self.normalize_symbol(pair)
        try:
            tick = await self._fetch_ticker_v3(symbol)
            if tick is None:
                tick = await self._fetch_books_top1(symbol)
            return {"exchange": self.name, "raw_symbol": symbol, **tick}
        finally:
            if self._own_session and self._session:
                await self._session.close()
                self._session = None
                self._own_session = False

    async def stream_book_ticker(self, pair: str):
        symbol = self.normalize_symbol(pair)
        backoff = 1.0
        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(self.WS_PUBLIC, heartbeat=20) as ws:
                        await ws.send_json({"op": "subscribe", "args": [f"spot/ticker:{symbol}"]})
                        print(f"[WS:BITMART] Subscribed to spot/ticker:{symbol}")
                        backoff = 1.0
                        async for msg in ws:
                            text = None
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                text = msg.data
                            elif msg.type == aiohttp.WSMsgType.BINARY:
                                import gzip, zlib
                                try:
                                    text = gzip.decompress(msg.data).decode("utf-8", "ignore")
                                except Exception:
                                    try:
                                        text = zlib.decompress(msg.data, -zlib.MAX_WBITS).decode("utf-8", "ignore")
                                    except Exception:
                                        continue
                            else:
                                continue
                            try:
                                data = json.loads(text)
                            except Exception:
                                continue
                            if isinstance(data, dict) and data.get("table") == "spot/ticker":
                                for item in data.get("data", []):
                                    bid = float(item.get("bid_px"))
                                    ask = float(item.get("ask_px"))
                                    ts = int(item.get("ts", int(time.time() * 1000)))
                                    yield {"exchange": self.name, "symbol": symbol, "bid": bid, "ask": ask, "timestamp": ts}
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                print(f"[WS:BITMART] {type(e).__name__}: {e}. Reconnecting in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


# Binance (REST + WS) with dual-source support
class BinanceConnector(ExchangeConnector):
    name = "binance"
    WS_PUBLIC = "wss://stream.binance.com:9443/ws"
    WS_US = "wss://stream.binance.us:9443/ws"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, timeout_s: float = 3.0):
        self._session = session
        self._own_session = False
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {"User-Agent": "bba/1.0"}

    def normalize_symbol(self, pair: str) -> str:
        s = pair.replace("-", "").replace("_", "").replace("/", "").upper()
        return s

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers, timeout=self._timeout)
            self._own_session = True

    async def _fetch_server_time(self, symbol: str) -> int:
        try:
            data = await binance_dual.fetch_json(self._session, symbol, "/api/v3/time")
            return int(data.get("serverTime", time.time() * 1000))
        except Exception:
            return int(time.time() * 1000)

    async def _fetch_book_ticker(self, symbol: str) -> Dict[str, Any]:
        data = await binance_dual.fetch_json(self._session, symbol, "/api/v3/ticker/bookTicker", {"symbol": symbol})
        bid = float(data["bidPrice"])
        ask = float(data["askPrice"])
        return {"bid": bid, "ask": ask}

    async def get_best_bid_ask(self, pair: str) -> Dict[str, Any]:
        await self._ensure_session()
        symbol = self.normalize_symbol(pair)
        try:
            tick = await self._fetch_book_ticker(symbol)
            ts_ms = await self._fetch_server_time(symbol)
            return {"exchange": self.name, "raw_symbol": symbol, "timestamp": ts_ms, **tick}
        finally:
            if self._own_session and self._session:
                await self._session.close()
                self._session = None
                self._own_session = False

    async def stream_book_ticker(self, pair: str):
        symbol = self.normalize_symbol(pair)
        stream = f"{symbol.lower()}@bookTicker"
        
        # Determine which WebSocket endpoint to use based on symbol availability
        await self._ensure_session()
        await binance_dual.initialize_cache(self._session)
        
        # Try global WS first, then US if symbol exists there
        ws_urls = []
        if symbol in binance_dual.global_spot_symbols:
            ws_urls.append(f"{self.WS_PUBLIC}/{stream}")
        if symbol in binance_dual.us_spot_symbols:
            ws_urls.append(f"{self.WS_US}/{stream}")
        
        if not ws_urls:
            # Symbol not in cache, try both
            ws_urls = [f"{self.WS_PUBLIC}/{stream}", f"{self.WS_US}/{stream}"]
        
        if self._own_session and self._session:
            await self._session.close()
            self._session = None
            self._own_session = False
        
        backoff = 1.0
        url_idx = 0
        
        while True:
            url = ws_urls[url_idx % len(ws_urls)]
            source = "binance.com" if "binance.com" in url else "binance.us"
            
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=20) as ws:
                        print(f"[WS:BINANCE] {symbol}: connected to {source}")
                        backoff = 1.0
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                data = json.loads(msg.data)
                            except Exception:
                                continue
                            if "b" in data and "a" in data:
                                bid = float(data["b"])
                                ask = float(data["a"])
                                ts = int(time.time() * 1000)
                                yield {"exchange": self.name, "symbol": symbol, "bid": bid, "ask": ask, "timestamp": ts}
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                print(f"[WS:BINANCE] {symbol}: {source} failed ({type(e).__name__}: {e}). Reconnecting in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                # Try next URL on reconnection
                url_idx += 1


# Deribit (REST + WS)
class DeribitConnector(ExchangeConnector):
    name = "deribit"
    REST_BASE = "https://www.deribit.com/api/v2"
    WS_PUBLIC = "wss://www.deribit.com/ws/api/v2"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, timeout_s: float = 3.0):
        self._session = session
        self._own_session = False
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {"User-Agent": "bba/1.0"}

    def normalize_symbol(self, pair_or_instr: str) -> str:
        s = pair_or_instr.strip().upper().replace("_", "-")
        # If already a Deribit instrument, return as-is
        if "-PERPETUAL" in s or ("-" in s and len(s.split("-")) > 2):
            return s
        # Convert spot pairs to perpetuals
        if "USDT" in s or "USD" in s or "/" in s or "_" in s:
            base = s.replace("/", "-").replace("_", "-").replace("USDT", "").replace("USD", "").split("-")[0]
            perp = f"{base}-PERPETUAL"
            print(f"[DERIBIT] Converting {pair_or_instr} -> {perp}")
            return perp
        # Single token (e.g., "BTC") -> BTC-PERPETUAL
        if s.isalpha():
            perp = f"{s}-PERPETUAL"
            print(f"[DERIBIT] Converting {pair_or_instr} -> {perp}")
            return perp
        return s

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers, timeout=self._timeout)
            self._own_session = True

    async def _get_json(self, path: str, params: dict) -> dict:
        url = f"{self.REST_BASE}{path}"
        async with self._session.get(url, params=params) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"[Deribit] HTTP {resp.status}: {text[:300]}")
            try:
                return await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                return json.loads(text)

    async def _fetch_ticker(self, instrument: str) -> Optional[Dict[str, Any]]:
        data = await self._get_json("/public/ticker", {"instrument_name": instrument})
        result = data.get("result") or data.get("data") or {}
        bid = result.get("best_bid_price") or result.get("bid_price")
        ask = result.get("best_ask_price") or result.get("ask_price")
        ts = result.get("timestamp")
        if bid is None or ask is None:
            return None
        return {"bid": float(bid), "ask": float(ask), "timestamp": int(ts) if ts is not None else int(time.time() * 1000), "raw": result}

    async def _fetch_order_book_top1(self, instrument: str) -> Dict[str, Any]:
        data = await self._get_json("/public/get_order_book", {"instrument_name": instrument, "depth": 1})
        result = data.get("result") or {}
        bids = result.get("bids") or []
        asks = result.get("asks") or []
        if not bids or not asks:
            raise RuntimeError(f"[Deribit] missing bids/asks for {instrument}: {result}")
        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        ts = int(result.get("timestamp", int(time.time() * 1000)))
        return {"bid": best_bid, "ask": best_ask, "timestamp": ts, "raw": result}

    async def get_best_bid_ask(self, pair_or_instr: str) -> Dict[str, Any]:
        await self._ensure_session()
        instrument = self.normalize_symbol(pair_or_instr)
        try:
            tick = await self._fetch_ticker(instrument)
            if tick is None:
                tick = await self._fetch_order_book_top1(instrument)
            return {"exchange": self.name, "raw_symbol": instrument, **tick}
        finally:
            if self._own_session and self._session:
                await self._session.close()
                self._session = None
                self._own_session = False

    async def stream_book_ticker(self, pair_or_instr: str):
        instrument = self.normalize_symbol(pair_or_instr)
        channels = [f"ticker.{instrument}.100ms", f"ticker.{instrument}.raw"]
        backoff = 1.0
        NO_TICK_WARN_SECS = 10

        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(self.WS_PUBLIC, heartbeat=20) as ws:
                        print(f"[WS:DERIBIT] Connected. Subscribing to {', '.join(channels)}")
                        # Seed snapshot so you see something immediately
                        try:
                            snap = await self._fetch_ticker(instrument) or await self._fetch_order_book_top1(instrument)
                            yield {"exchange": self.name, "symbol": instrument, "bid": snap["bid"], "ask": snap["ask"], "timestamp": snap["timestamp"]}
                        except Exception as e:
                            print(f"[WS:DERIBIT] Seed snapshot failed: {e}")

                        await ws.send_json({"jsonrpc":"2.0","id":1,"method":"public/set_heartbeat","params":{"interval":10}})
                        await ws.send_json({"jsonrpc":"2.0","id":2,"method":"public/subscribe","params":{"channels":channels}})
                        subscribed = False
                        last_tick_ts = time.time()
                        backoff = 1.0

                        while True:
                            if time.time() - last_tick_ts > NO_TICK_WARN_SECS:
                                print(f"[WS:DERIBIT] No book changes in {NO_TICK_WARN_SECS}s for {instrument}. Waiting…")
                                last_tick_ts = time.time()
                            msg = await ws.receive(timeout=15)
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                raise ConnectionError("WS closed/error")
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                data = json.loads(msg.data)
                            except Exception:
                                continue
                            if data.get("method") == "heartbeat":
                                if data.get("params", {}).get("type") == "test_request":
                                    await ws.send_json({"jsonrpc":"2.0","id":3,"method":"public/test","params":{}})
                                continue
                            if data.get("id") == 2 and "result" in data and not subscribed:
                                print(f"[WS:DERIBIT] Subscribed OK.")
                                subscribed = True
                                continue
                            if data.get("method") == "subscription":
                                params = data.get("params", {})
                                ch = params.get("channel", "")
                                if ch not in channels:
                                    continue
                                d = params.get("data", {})
                                bid = d.get("best_bid_price") or d.get("bid_price")
                                ask = d.get("best_ask_price") or d.get("ask_price")
                                if bid is None or ask is None:
                                    continue
                                ts = int(d.get("timestamp", int(time.time() * 1000)))
                                last_tick_ts = time.time()
                                yield {"exchange": self.name, "symbol": instrument, "bid": float(bid), "ask": float(ask), "timestamp": ts}
            except (asyncio.TimeoutError, ConnectionError, aiohttp.ClientError) as e:
                print(f"[WS:DERIBIT] {type(e).__name__}: {e}. Reconnecting in {backoff:.0f}s …")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


# KuCoin (REST + WS)
class KucoinConnector(ExchangeConnector):
    name = "kucoin"
    REST_BASE = "https://api.kucoin.com"
    BULLET_PUBLIC = "/api/v1/bullet-public"  # POST

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, timeout_s: float = 4.0):
        self._session = session
        self._own_session = False
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {"User-Agent": "bba/1.0"}

    def normalize_symbol(self, pair: str) -> str:
        s = pair.replace("_", "-").replace("/", "-").upper()
        if "-" not in s:
            for q in ("USDT", "USDC", "BTC", "ETH", "USD"):
                if s.endswith(q) and len(s) > len(q):
                    s = f"{s[:-len(q)]}-{q}"
                    break
        return s

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers, timeout=self._timeout)
            self._own_session = True

    async def _get_json(self, path: str, params: dict = None, method: str = "GET") -> dict:
        await self._ensure_session()
        url = f"{self.REST_BASE}{path}"
        if method == "GET":
            async with self._session.get(url, params=params) as resp:
                text = await resp.text()
        else:
            async with self._session.post(url, json=params or {}) as resp:
                text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"[KuCoin] HTTP {resp.status}: {text[:300]}")
        try:
            return json.loads(text)
        except Exception:
            return await resp.json()

    async def _fetch_level1(self, symbol: str) -> Dict[str, Any]:
        data = await self._get_json("/api/v1/market/orderbook/level1", {"symbol": symbol}, "GET")
        if data.get("code") != "200000":
            raise RuntimeError(f"[KuCoin] Unexpected level1 response: {data}")
        d = data.get("data") or {}
        bid = float(d["bestBid"])
        ask = float(d["bestAsk"])
        ts = int(d.get("time", int(time.time() * 1000)))
        return {"bid": bid, "ask": ask, "timestamp": ts, "raw": d}

    async def _fetch_server_time(self) -> int:
        try:
            data = await self._get_json("/api/v1/timestamp", {}, "GET")
            if data.get("code") == "200000":
                return int(data["data"])
        except Exception:
            pass
        return int(time.time() * 1000)

    async def get_best_bid_ask(self, pair: str) -> Dict[str, Any]:
        symbol = self.normalize_symbol(pair)
        try:
            res = await self._fetch_level1(symbol)
            ts = res["timestamp"] or await self._fetch_server_time()
            return {"exchange": self.name, "raw_symbol": symbol, "bid": res["bid"], "ask": res["ask"], "timestamp": ts}
        finally:
            if self._own_session and self._session:
                await self._session.close()
                self._session = None
                self._own_session = False

    async def _get_ws_endpoint(self) -> Dict[str, Any]:
        data = await self._get_json("/api/v1/bullet-public", {}, "POST")
        if data.get("code") != "200000":
            raise RuntimeError(f"[KuCoin] bullet-public error: {data}")
        d = data["data"]
        token = d["token"]
        servers = d["instanceServers"]
        if not servers:
            raise RuntimeError("[KuCoin] No instanceServers returned")
        server = servers[0]
        endpoint = server["endpoint"]
        ping_interval = int(server.get("pingInterval", 20000))
        return {"endpoint": endpoint, "token": token, "pingInterval": ping_interval}

    async def stream_book_ticker(self, pair: str):
        symbol = self.normalize_symbol(pair)
        topics = [f"/spotMarket/level1:{symbol}", f"/market/ticker:{symbol}"]
        backoff = 1.0

        def _decode(msg) -> Optional[str]:
            if msg.type == aiohttp.WSMsgType.TEXT:
                return msg.data
            if msg.type == aiohttp.WSMsgType.BINARY:
                import gzip, zlib
                b = msg.data
                try:
                    return gzip.decompress(b).decode("utf-8", "ignore")
                except Exception:
                    try:
                        return zlib.decompress(b, -zlib.MAX_WBITS).decode("utf-8", "ignore")
                    except Exception:
                        return None
            return None

        while True:
            try:
                ws_info = await self._get_ws_endpoint()
                endpoint = ws_info["endpoint"]
                token = ws_info["token"]
                ping_interval = ws_info["pingInterval"]
                connect_id = str(uuid.uuid4())
                url = f"{endpoint}?token={token}&connectId={connect_id}"

                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(url, heartbeat=None) as ws:
                        print(f"[WS:KUCOIN] Connected.")
                        # subscribe EACH topic separately
                        for t in topics:
                            await ws.send_json({"id": str(uuid.uuid4()), "type": "subscribe",
                                                "topic": t, "privateChannel": False, "response": True})
                            print(f"[WS:KUCOIN] Subscribing to {t}")

                        async def ping_loop():
                            while True:
                                await asyncio.sleep(ping_interval / 1000.0)
                                try:
                                    await ws.send_json({"id": str(uuid.uuid4()), "type": "ping"})
                                except Exception:
                                    break
                        ptask = asyncio.create_task(ping_loop())
                        backoff = 1.0

                        async for msg in ws:
                            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            text = _decode(msg)
                            if not text:
                                continue
                            try:
                                data = json.loads(text)
                            except Exception:
                                continue

                            if data.get("type") == "ping":
                                await ws.send_json({"id": str(uuid.uuid4()), "type": "pong"})
                                continue
                            if data.get("type") == "ack":
                                print("[WS:KUCOIN] ACK received")
                                continue
                            if data.get("type") == "error":
                                print(f"[WS:KUCOIN] ERROR: {data}")
                                continue

                            if data.get("type") == "message" and data.get("topic") in topics:
                                payload = data.get("data", {})
                                bid = payload.get("bestBid")
                                ask = payload.get("bestAsk")
                                if bid is None or ask is None:
                                    continue
                                ts = int(payload.get("time", int(time.time() * 1000)))
                                yield {"exchange": self.name, "symbol": symbol, "bid": float(bid),
                                       "ask": float(ask), "timestamp": ts}
                        ptask.cancel()
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError, RuntimeError) as e:
                print(f"[WS:KUCOIN] {type(e).__name__}: {e}. Reconnecting in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)



# OKX (REST + WS)
class OkxConnector(ExchangeConnector):
    """
    OKX SPOT best bid/ask.
    REST: GET https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT
          Fallback: GET /api/v5/market/books?instId=BTC-USDT&sz=1
    WS:   wss://ws.okx.com:8443/ws/v5/public
          subscribe: {"op":"subscribe","args":[{"channel":"tickers","instId":"BTC-USDT"}]}
    """
    name = "okx"
    REST_BASE = "https://www.okx.com"
    WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, timeout_s: float = 4.0):
        self._session = session
        self._own_session = False
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {"User-Agent": "bba/1.0"}

    def normalize_symbol(self, pair: str) -> str:
        # OKX wants hyphenated uppercase: BTC-USDT
        s = pair.replace("_", "-").replace("/", "-").upper()
        if "-" not in s:
            for q in ("USDT", "USDC", "BTC", "ETH", "USD"):
                if s.endswith(q) and len(s) > len(q):
                    s = f"{s[:-len(q)]}-{q}"
                    break
        return s

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            # Disable SSL verification and add more headers to bypass geo-blocking
            connector = aiohttp.TCPConnector(ssl=False)
            headers = {
                **self._headers,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site"
            }
            print("[OKX] Using SSL bypass and enhanced headers for geo-blocking issues")
            self._session = aiohttp.ClientSession(headers=headers, timeout=self._timeout, connector=connector)
            self._own_session = True

    async def _get_json(self, path: str, params: dict) -> dict:
        await self._ensure_session()
        url = f"{self.REST_BASE}{path}"
        async with self._session.get(url, params=params) as resp:
            text = await resp.text()
            if resp.status == 403:
                raise RuntimeError(f"[OKX] Access blocked (403) - Your IP/region may be restricted by OKX. Try VPN or different network.")
            if resp.status != 200:
                raise RuntimeError(f"[OKX] HTTP {resp.status}: {text[:300]}")
            try:
                return await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                return json.loads(text)

    async def _fetch_ticker(self, inst_id: str) -> Optional[Dict[str, Any]]:
        data = await self._get_json("/api/v5/market/ticker", {"instId": inst_id})
        if data.get("code") != "0" or not data.get("data"):
            return None
        d = data["data"][0]
        bp, ap, ts = d.get("bidPx"), d.get("askPx"), d.get("ts")
        if bp is None or ap is None:
            return None
        return {"bid": float(bp), "ask": float(ap), "timestamp": int(ts) if ts else int(time.time()*1000), "raw": d}

    async def _fetch_books_top1(self, inst_id: str) -> Dict[str, Any]:
        data = await self._get_json("/api/v5/market/books", {"instId": inst_id, "sz": 1})
        if data.get("code") != "0" or not data.get("data"):
            raise RuntimeError(f"[OKX] Unexpected books response: {data}")
        d = data["data"][0]
        bids, asks = d.get("bids") or [], d.get("asks") or []
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        ts_ms = int(d.get("ts", int(time.time() * 1000)))
        return {"bid": best_bid, "ask": best_ask, "timestamp": ts_ms, "raw": d}

    async def get_best_bid_ask(self, pair: str) -> Dict[str, Any]:
        inst = self.normalize_symbol(pair)
        try:
            tick = await self._fetch_ticker(inst)
            if tick is None:
                tick = await self._fetch_books_top1(inst)
            return {"exchange": self.name, "raw_symbol": inst, **tick}
        finally:
            if self._own_session and self._session:
                await self._session.close()
                self._session = None
                self._own_session = False

    async def stream_book_ticker(self, pair: str):
        inst = self.normalize_symbol(pair)
        args = [{"channel": "tickers", "instId": inst}]
        backoff = 1.0

        def _decode(msg) -> Optional[str]:
            if msg.type == aiohttp.WSMsgType.TEXT:
                return msg.data
            if msg.type == aiohttp.WSMsgType.BINARY:
                import gzip, zlib
                b = msg.data
                try:
                    return gzip.decompress(b).decode("utf-8", "ignore")
                except Exception:
                    try:
                        return zlib.decompress(b, -zlib.MAX_WBITS).decode("utf-8", "ignore")
                    except Exception:
                        return None
            return None

        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(self.WS_PUBLIC, heartbeat=20) as ws:
                        sub = {"op": "subscribe", "args": args}
                        await ws.send_json(sub)
                        print(f"[WS:OKX] Subscribed to tickers:{inst}")
                        backoff = 1.0

                        # Seed REST snapshot so you see something immediately
                        try:
                            snap = await self._fetch_ticker(inst) or await self._fetch_books_top1(inst)
                            yield {"exchange": self.name, "symbol": inst, "bid": snap["bid"], "ask": snap["ask"], "timestamp": snap["timestamp"]}
                        except Exception as e:
                            print(f"[WS:OKX] Seed snapshot failed: {e}")

                        async for msg in ws:
                            text = _decode(msg)
                            if not text:
                                continue
                            try:
                                data = json.loads(text)
                            except Exception:
                                continue

                            # OKX sends event acks: {"event":"subscribe","arg":{...}}
                            if data.get("event") == "subscribe":
                                continue

                            if "arg" in data and "data" in data and data["arg"].get("channel") == "tickers":
                                for d in data["data"]:
                                    bp, ap, ts = d.get("bidPx"), d.get("askPx"), d.get("ts")
                                    if bp is None or ap is None:
                                        continue
                                    yield {"exchange": self.name, "symbol": inst, "bid": float(bp),
                                           "ask": float(ap), "timestamp": int(ts) if ts else int(time.time()*1000)}
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                print(f"[WS:OKX] {type(e).__name__}: {e}. Reconnecting in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


# Hyperliquid (REST + WS)
class HyperliquidConnector(ExchangeConnector):
    """
    Hyperliquid DEX best bid/ask.
    REST: POST https://api.hyperliquid.xyz/info (public)
    WS:   wss://api.hyperliquid.xyz/ws
    """
    name = "hyperliquid"
    REST_BASE = "https://api.hyperliquid.xyz"
    WS_BASE = "wss://api.hyperliquid.xyz/ws"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, timeout_s: float = 4.0):
        self._session = session
        self._own_session = False
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {"User-Agent": "bba/1.0", "Content-Type": "application/json"}

    def normalize_symbol(self, pair: str) -> str:
        # Hyperliquid uses symbols like "BTC", "ETH", "SOL"
        s = pair.upper().replace("-", "").replace("_", "").replace("/", "")
        # Remove common quote currencies to get base
        for quote in ("USDT", "USDC", "USD", "PERP", "PERPETUAL"):
            if s.endswith(quote):
                s = s[:-len(quote)]
                break
        print(f"[HYPERLIQUID] Converting {pair} -> {s}")
        return s

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers, timeout=self._timeout)
            self._own_session = True

    async def _post_json(self, path: str, payload: dict) -> dict:
        await self._ensure_session()
        url = f"{self.REST_BASE}{path}"
        async with self._session.post(url, json=payload) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"[Hyperliquid] HTTP {resp.status}: {text[:300]}")
            try:
                return await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                return json.loads(text)

    async def _fetch_l2_book(self, coin: str) -> Dict[str, Any]:
        payload = {
            "type": "l2Book",
            "coin": coin
        }
        data = await self._post_json("/info", payload)
        
        if not data or "levels" not in data:
            raise RuntimeError(f"[Hyperliquid] Invalid l2Book response: {data}")
        
        levels = data["levels"]
        
        # Handle both dict and list formats
        if isinstance(levels, dict):
            bids = levels.get("bids", [])
            asks = levels.get("asks", [])
        elif isinstance(levels, list) and len(levels) >= 2:
            bids = levels[0] if levels[0] else []
            asks = levels[1] if levels[1] else []
        else:
            raise RuntimeError(f"[Hyperliquid] Unexpected levels format: {levels}")
        
        if not bids or not asks:
            raise RuntimeError(f"[Hyperliquid] No bids/asks for {coin}")
        
        # Hyperliquid format: [{"px": "50000.0", "sz": "1.5"}, ...] or [["50000.0", "1.5"], ...]
        if isinstance(bids[0], dict):
            best_bid = float(bids[0]["px"])
            best_ask = float(asks[0]["px"])
        elif isinstance(bids[0], list):
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
        else:
            raise RuntimeError(f"[Hyperliquid] Unexpected bid/ask format: {bids[0]}")
        
        return {
            "bid": best_bid,
            "ask": best_ask,
            "timestamp": int(time.time() * 1000),
            "raw": data
        }

    async def _fetch_all_mids(self) -> Dict[str, Any]:
        """Fallback: get all market prices at once"""
        payload = {"type": "allMids"}
        return await self._post_json("/info", payload)

    async def get_best_bid_ask(self, pair: str) -> Dict[str, Any]:
        coin = self.normalize_symbol(pair)
        try:
            # Try L2 book first (more accurate)
            try:
                tick = await self._fetch_l2_book(coin)
            except Exception:
                # Fallback to allMids
                all_mids = await self._fetch_all_mids()
                if coin not in all_mids:
                    available = list(all_mids.keys())[:10]  # Show first 10
                    raise RuntimeError(f"[Hyperliquid] Coin '{coin}' not found. Available: {available}")
                
                mid_price = float(all_mids[coin])
                # Estimate bid/ask with small spread (this is approximate)
                spread = mid_price * 0.0001  # 1 bps spread estimate
                tick = {
                    "bid": mid_price - spread/2,
                    "ask": mid_price + spread/2,
                    "timestamp": int(time.time() * 1000),
                    "raw": {"mid": mid_price, "estimated": True}
                }
            
            return {"exchange": self.name, "raw_symbol": coin, **tick}
        finally:
            if self._own_session and self._session:
                await self._session.close()
                self._session = None
                self._own_session = False

    async def stream_book_ticker(self, pair: str):
        coin = self.normalize_symbol(pair)
        backoff = 1.0
        
        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(self.WS_BASE, heartbeat=20) as ws:
                        # Subscribe to L2 book for the coin
                        subscribe_msg = {
                            "method": "subscribe",
                            "subscription": {
                                "type": "l2Book",
                                "coin": coin
                            }
                        }
                        await ws.send_json(subscribe_msg)
                        print(f"[WS:HYPERLIQUID] Subscribed to l2Book:{coin}")
                        
                        # Send initial snapshot request
                        try:
                            snap = await self._fetch_l2_book(coin)
                            yield {"exchange": self.name, "symbol": coin, "bid": snap["bid"], 
                                  "ask": snap["ask"], "timestamp": snap["timestamp"]}
                        except Exception as e:
                            print(f"[WS:HYPERLIQUID] Initial snapshot failed: {e}")
                        
                        backoff = 1.0
                        
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                data = json.loads(msg.data)
                            except Exception:
                                continue
                            
                            # Hyperliquid WS format varies, handle different message types
                            if data.get("channel") == "l2Book" and data.get("data"):
                                book_data = data["data"]
                                if "levels" in book_data:
                                    levels = book_data["levels"]
                                    
                                    # Handle both dict and list formats
                                    if isinstance(levels, dict):
                                        bids = levels.get("bids", [])
                                        asks = levels.get("asks", [])
                                    elif isinstance(levels, list) and len(levels) >= 2:
                                        bids = levels[0] if levels[0] else []
                                        asks = levels[1] if levels[1] else []
                                    else:
                                        continue
                                    
                                    if bids and asks:
                                        try:
                                            # Handle different bid/ask formats
                                            if isinstance(bids[0], dict):
                                                bid = float(bids[0]["px"])
                                                ask = float(asks[0]["px"])
                                            elif isinstance(bids[0], list):
                                                bid = float(bids[0][0])
                                                ask = float(asks[0][0])
                                            else:
                                                continue
                                            
                                            ts = int(time.time() * 1000)
                                            yield {"exchange": self.name, "symbol": coin, 
                                                  "bid": bid, "ask": ask, "timestamp": ts}
                                        except (ValueError, IndexError, KeyError):
                                            continue
                            
            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                print(f"[WS:HYPERLIQUID] {type(e).__name__}: {e}. Reconnecting in {backoff:.0f}s ...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


# Aggregation helpers
def validate_token_format(token: str) -> bool:
    """Basic token format validation"""
    import re
    # Allow alphanumeric, hyphens, underscores, slashes, and common patterns
    valid_pattern = re.compile(r'^[A-Za-z0-9/_-]+$')
    
    # Check for invalid characters
    if not valid_pattern.match(token):
        return False
    
    # Check for reasonable length (3-20 characters)
    if len(token) < 3 or len(token) > 20:
        return False
    
    return True

async def print_rest_snapshot(connectors: List[ExchangeConnector], pair_or_instr: str):
    # Validate token format first
    if not validate_token_format(pair_or_instr):
        print(f"[ERROR] Invalid token format: {pair_or_instr}", file=sys.stderr)
        print("Valid formats: BTCUSDT, BTC-USDT, BTC/USDT, BTC_USDT, BTC-PERPETUAL", file=sys.stderr)
        return
    
    results = []
    for c in connectors:
        try:
            res = await c.get_best_bid_ask(pair_or_instr)
            bid, ask = res["bid"], res["ask"]
            mid = (bid + ask) / 2
            t = ms_to_pretty(res["timestamp"])
            print(f"{c.name.upper()} | Input: {pair_or_instr} (normalized: {res['raw_symbol']})")
            print(f"  Best Bid: {bid}")
            print(f"  Best Ask: {ask}")
            print(f"  Mid:      {mid}")
            print(f"  Timestamp(ms): {res['timestamp']}")
            print(f"  UTC: {t['utc']}")
            print(f"  IST: {t['ist']}")
            print(f"  Age: {t['ago']}")
            print("")
            results.append((c.name, bid, ask))
        except Exception as e:
            print(f"[ERROR] {c.name}: {e}", file=sys.stderr)

    if results:
        # Separate spot and perpetual results
        spot_results = [(n, b, a) for n, b, a in results if n != "deribit"]
        perp_results = [(n, b, a) for n, b, a in results if n == "deribit"]
        
        print("=== Aggregated Across Exchanges ===")
        
        # Show spot-only aggregation
        if spot_results:
            best_bid_exch, best_bid = max(((n, b) for n, b, _ in spot_results), key=lambda x: x[1])
            best_ask_exch, best_ask = min(((n, a) for n, _, a in spot_results), key=lambda x: x[1])
            agg_mid = (best_bid + best_ask) / 2
            print(f"  SPOT MARKETS:")
            print(f"    Best Bid: {best_bid} on {best_bid_exch}")
            print(f"    Best Ask: {best_ask} on {best_ask_exch}")
            print(f"    Mid:      {agg_mid}")
        
        # Show perpetual results separately
        if perp_results:
            perp_bid_exch, perp_bid = max(((n, b) for n, b, _ in perp_results), key=lambda x: x[1])
            perp_ask_exch, perp_ask = min(((n, a) for n, _, a in perp_results), key=lambda x: x[1])
            perp_mid = (perp_bid + perp_ask) / 2
            print(f"  PERPETUAL FUTURES (Deribit):")
            print(f"    Best Bid: {perp_bid} on {perp_bid_exch}")
            print(f"    Best Ask: {perp_ask} on {perp_ask_exch}")
            print(f"    Mid:      {perp_mid}")
        
        # Show overall best if both types exist
        if spot_results and perp_results:
            print(f"  NOTE: Spot and perpetual prices may differ due to funding rates and market structure")

async def stream_ws(connectors: List[ExchangeConnector], pair_or_instr: str):
    async def runner(conn: ExchangeConnector):
        async for tick in conn.stream_book_ticker(pair_or_instr):
            bid, ask = tick["bid"], tick["ask"]
            mid = (bid + ask) / 2
            t = ms_to_pretty(tick["timestamp"])
            print(f"[WS] {conn.name.upper()} {tick['symbol']} bid={bid} ask={ask} mid={mid} | UTC={t['utc']} | IST={t['ist']} | {t['ago']}")

    tasks = [asyncio.create_task(runner(c)) for c in connectors]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        for t in tasks:
            t.cancel()
        raise e


# CLI
def main():
    p = argparse.ArgumentParser(description="Best Bid/Ask via REST and WebSocket (BitMart + Binance + Deribit + KuCoin + OKX + Hyperliquid)")
    p.add_argument("input", help="Pair or instrument, e.g., BTC-USDT (spot-style) or BTC-PERPETUAL (Deribit)")
    p.add_argument("--ws", action="store_true", help="Use WebSocket streaming instead of REST snapshot")
    p.add_argument("--exch",
                   choices=["bitmart","binance","deribit","kucoin","okx","hyperliquid","both","all"],
                   default="all",
                   help="Which exchange(s) to query/stream ('both' = BitMart+Binance, 'all' = all 6 exchanges)")
    args = p.parse_args()

    connectors: List[ExchangeConnector] = []
    if args.exch in ("bitmart", "both", "all"):
        connectors.append(BitmartConnector())
    if args.exch in ("binance", "both", "all"):
        connectors.append(BinanceConnector())
    if args.exch in ("deribit", "all"):
        connectors.append(DeribitConnector())
    if args.exch in ("kucoin", "all"):
        connectors.append(KucoinConnector())
    if args.exch in ("okx", "all"):
        connectors.append(OkxConnector())
    if args.exch in ("hyperliquid", "all"):
        connectors.append(HyperliquidConnector())

    if args.ws:
        asyncio.run(stream_ws(connectors, args.input))
    else:
        asyncio.run(print_rest_snapshot(connectors, args.input))


if __name__ == "__main__":
    main()
