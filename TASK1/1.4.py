#!/usr/bin/env python3
import asyncio
import aiohttp
import argparse
import time
import json
from typing import List, Tuple, Dict, Any, Optional

###############################################################################
# Utility helpers
###############################################################################

def now_ms() -> int:
    return int(time.time() * 1000)

def norm_binance_symbol(pair: str) -> str:
    return pair.replace("-", "").replace("_", "").replace("/", "").upper()

def norm_bybit_symbol(pair: str) -> str:
    return pair.replace("-", "").replace("_", "").replace("/", "").upper()

def norm_kucoin_symbol(pair: str) -> str:
    s = pair.replace("_", "-").replace("/", "-").upper()
    if "-" not in s:
        for q in ("USDT", "USDC", "BTC", "ETH", "USD"):
            if s.endswith(q) and len(s) > len(q):
                s = f"{s[:-len(q)]}-{q}"
                break
    return s

class UnsupportedInstrument(ValueError):
    """Raised when the requested symbol doesn't exist on Deribit."""

def norm_deribit_instrument(s: str) -> str:
    """
    Accepts BTC-USDT / BTCUSDT / BTC-PERPETUAL / BTC-27SEP24 etc.
    For Deribit we map to <BASE>-PERPETUAL when the input looks spot-ish.
    """
    s0 = s.upper().replace("/", "-").replace("_", "-")
    if "PERPETUAL" in s0:
        # normalize like BTC-PERPETUAL
        parts = s0.split("-")
        base = parts[0]
        return f"{base}-PERPETUAL"
    # If looks like a dated future already (BTC-27SEP24...), just return as-is
    if "-" in s0 and s0.split("-")[1][:2].isdigit():
        return s0
    # Otherwise infer base from the left token and map to PERPETUAL
    base = s0.split("-")[0]
    for q in ("USDT", "USD", "USDC"):
        if base.endswith(q):
            base = base[:-len(q)]
    if base not in ("BTC", "ETH"):
        raise UnsupportedInstrument(f"Deribit has no perpetual for {base}")
    return f"{base}-PERPETUAL"

def compute_mid(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> float:
    if not bids or not asks:
        return float("nan")
    return (bids[0][0] + asks[0][0]) / 2.0

def walk_book_buy(asks: List[Tuple[float, float]], quote_volume: float):
    remaining_q = float(quote_volume)
    base_bought = 0.0
    quote_spent = 0.0
    levels_used = 0
    for price, qty_base in asks:
        if remaining_q <= 1e-12:
            break
        # quote capacity at level
        level_quote_cap = price * qty_base
        take_q = min(remaining_q, level_quote_cap)
        take_base = take_q / price
        base_bought += take_base
        quote_spent += take_q
        remaining_q -= take_q
        levels_used += 1
    if base_bought <= 0:
        return float("nan"), levels_used, base_bought, quote_spent, False
    avg_price = quote_spent / base_bought
    return avg_price, levels_used, base_bought, quote_spent, remaining_q <= 1e-9

def walk_book_sell(bids: List[Tuple[float, float]], quote_volume: float):
    remaining_q = float(quote_volume)
    base_sold = 0.0
    quote_recv = 0.0
    levels_used = 0
    for price, qty_base in bids:
        if remaining_q <= 1e-12:
            break
        level_quote_cap = price * qty_base
        take_q = min(remaining_q, level_quote_cap)
        take_base = take_q / price
        base_sold += take_base
        quote_recv += take_q
        remaining_q -= take_q
        levels_used += 1
    if base_sold <= 0:
        return float("nan"), levels_used, base_sold, quote_recv, False
    avg_price = quote_recv / base_sold
    return avg_price, levels_used, base_sold, quote_recv, remaining_q <= 1e-9

def impact_metrics(avg_exec: float, mid: float, side: str) -> Dict[str, float]:
    if not (avg_exec > 0 and mid > 0):
        return {"impact_pct": float("nan"), "impact_bps": float("nan")}
    sign = 1.0 if side.lower() == "buy" else -1.0
    pct = sign * (abs(avg_exec - mid) / mid) * 100.0
    return {"impact_pct": pct, "impact_bps": pct * 100.0}

###############################################################################
# Exchange fetchers (public REST)
###############################################################################

class ExchangeL2:
    name = "exchange"
    async def fetch(self, session: aiohttp.ClientSession, pair: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

class BinanceL2(ExchangeL2):
    name = "binance"
    BASES = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://api4.binance.com",
        "https://api-gcp.binance.com",
    ]
    async def fetch(self, session: aiohttp.ClientSession, pair: str, limit: int = 5000, **_) -> Dict[str, Any]:
        symbol = norm_binance_symbol(pair)
        limit = max(1, min(int(limit), 5000))
        last_exc = None
        for base in self.BASES:
            try:
                url = f"{base}/api/v3/depth"
                async with session.get(url, params={"symbol": symbol, "limit": limit}) as r:
                    data = await r.json()
                bids = [(float(p), float(q)) for p, q, *_ in data.get("bids", [])]
                asks = [(float(p), float(q)) for p, q, *_ in data.get("asks", [])]
                bids.sort(key=lambda x: x[0], reverse=True)
                asks.sort(key=lambda x: x[0])
                return {"exchange": self.name, "symbol": symbol, "timestamp": now_ms(), "bids": bids, "asks": asks}
            except Exception as e:
                last_exc = e
                continue
        raise RuntimeError(f"[binance] depth failed on all bases: {last_exc}")

class BybitL2(ExchangeL2):
    name = "bybit"
    BASE = "https://api.bybit.com"
    async def fetch(self, session: aiohttp.ClientSession, pair: str, category: str = "spot", limit: int = None, **_) -> Dict[str, Any]:
        symbol = norm_bybit_symbol(pair)
        if limit is None:
            limit = 200 if category == "spot" else 500
        limit = max(1, min(int(limit), 500))
        url = f"{self.BASE}/v5/market/orderbook"
        params = {"category": category, "symbol": symbol, "limit": limit}
        async with session.get(url, params=params) as r:
            data = await r.json()
        if data.get("retCode") != 0:
            raise RuntimeError(f"[bybit] {data}")
        res = data.get("result") or {}
        bids = [(float(p), float(q)) for p, q in res.get("b", [])]
        asks = [(float(p), float(q)) for p, q in res.get("a", [])]
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])
        ts = int(res.get("ts") or now_ms())
        return {"exchange": self.name, "symbol": symbol, "timestamp": ts, "bids": bids, "asks": asks}

class KucoinL2(ExchangeL2):
    name = "kucoin"
    BASE = "https://api.kucoin.com"
    def _norm(self, pair: str) -> str:
        return norm_kucoin_symbol(pair)
    async def _get_json(self, session: aiohttp.ClientSession, path: str, params: dict) -> dict:
        url = f"{self.BASE}{path}"
        async with session.get(url, params=params, headers={"Accept": "application/json", "User-Agent": "impact/1.1"}) as r:
            text = await r.text()
            if r.status != 200:
                raise RuntimeError(f"[kucoin] HTTP {r.status}: {url} -> {text[:200]}")
            try:
                return json.loads(text)
            except Exception:
                return await r.json()
    async def fetch(self, session: aiohttp.ClientSession, pair: str, **_) -> Dict[str, Any]:
        symbol = self._norm(pair)
        for path in ("/api/v3/market/orderbook/level2_100",
                     "/api/v2/market/orderbook/level2_100",
                     "/api/v1/market/orderbook/level2_100"):
            try:
                data = await self._get_json(session, path, {"symbol": symbol})
                if data.get("code") == "200000":
                    d = data.get("data") or {}
                    bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
                    asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
                    bids.sort(key=lambda x: x[0], reverse=True)
                    asks.sort(key=lambda x: x[0])
                    ts = int(d.get("time") or now_ms())
                    return {"exchange": self.name, "symbol": symbol, "timestamp": ts, "bids": bids, "asks": asks}
            except Exception:
                continue
        raise RuntimeError("[kucoin] level2_100 not available on v3/v2/v1")

class DeribitL2(ExchangeL2):
    """
    Deribit inverse perps/futures. Use /public/get_order_book with 'depth'.
    'amount' is CONTRACTS; convert to base via base = contracts * contract_usd / price.
    """
    name = "deribit"
    BASE = "https://www.deribit.com/api/v2"
    async def _get_json(self, session: aiohttp.ClientSession, path: str, params: dict) -> dict:
        url = f"{self.BASE}{path}"
        async with session.get(url, params=params) as r:
            txt = await r.text()
            try:
                return json.loads(txt)
            except Exception:
                return await r.json()
    async def fetch(self, session: aiohttp.ClientSession, pair: str, limit: int = 50, deribit_contract_usd: float = 10.0, **_) -> Dict[str, Any]:
        instrument = norm_deribit_instrument(pair)
        depth = max(1, min(int(limit), 200))
        data = await self._get_json(session, "/public/get_order_book",
                                    {"instrument_name": instrument, "depth": depth})
        res = data.get("result") or {}
        # bids/asks may be list of dicts or list of [price, amount] pairs
        def _parse(side):
            arr = res.get(side) or []
            out = []
            for it in arr:
                if isinstance(it, dict):
                    price = float(it.get("price"))
                    contracts = float(it.get("amount"))
                else:
                    price = float(it[0]); contracts = float(it[1])
                # convert contracts -> base size
                base_qty = (contracts * deribit_contract_usd) / price if price > 0 else 0.0
                out.append((price, base_qty))
            return out
        bids = _parse("bids")
        asks = _parse("asks")
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])
        ts = int(res.get("timestamp") or now_ms())
        return {"exchange": self.name, "symbol": instrument, "timestamp": ts, "bids": bids, "asks": asks}

class HyperliquidL2(ExchangeL2):
    """
    Hyperliquid DEX perpetual futures. Uses /info endpoint with 'l2Book' type.
    Handles both dict and list response formats for levels and bid/ask entries.
    """
    name = "hyperliquid"
    BASE = "https://api.hyperliquid.xyz"
    
    def _norm_coin(self, pair: str) -> str:
        """Normalize symbol to Hyperliquid coin format (e.g., BTCUSDT -> BTC)"""
        s = pair.upper().replace("-", "").replace("_", "").replace("/", "")
        for q in ("USDT", "USDC", "USD"):
            if s.endswith(q):
                return s[:-len(q)]
        return s
    
    async def _get_json(self, session: aiohttp.ClientSession, payload: dict) -> dict:
        """POST request to Hyperliquid /info endpoint"""
        url = f"{self.BASE}/info"
        async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as r:
            r.raise_for_status()
            return await r.json()
    
    async def fetch(self, session: aiohttp.ClientSession, pair: str, limit: int = 50, **_) -> Dict[str, Any]:
        coin = self._norm_coin(pair)
        payload = {"type": "l2Book", "coin": coin}
        
        try:
            data = await self._get_json(session, payload)
            levels = data.get("levels") or {}
            
            # Handle both dict and list formats for levels
            if isinstance(levels, dict):
                bids = levels.get("bids", [])
                asks = levels.get("asks", [])
            elif isinstance(levels, list) and len(levels) >= 2:
                bids = levels[0] if isinstance(levels[0], list) else []
                asks = levels[1] if isinstance(levels[1], list) else []
            else:
                bids, asks = [], []
            
            # Parse bid/ask entries (can be dict or list format)
            def _parse_side(side_data):
                out = []
                for entry in side_data:
                    if isinstance(entry, dict):
                        price = float(entry.get("px", 0))
                        size = float(entry.get("sz", 0))
                    elif isinstance(entry, list) and len(entry) >= 2:
                        price = float(entry[0])
                        size = float(entry[1])
                    else:
                        continue
                    if price > 0 and size > 0:
                        out.append((price, size))
                return out
            
            bids = _parse_side(bids)
            asks = _parse_side(asks)
            
            # Sort by price
            bids.sort(key=lambda x: x[0], reverse=True)
            asks.sort(key=lambda x: x[0])
            
            # Limit depth if requested
            if limit and limit > 0:
                bids = bids[:limit]
                asks = asks[:limit]
            
            ts = now_ms()
            return {"exchange": self.name, "symbol": coin, "timestamp": ts, "bids": bids, "asks": asks}
            
        except Exception as e:
            raise RuntimeError(f"[hyperliquid] l2Book failed for {coin}: {e}")

###############################################################################
# Core computation
###############################################################################

async def fetch_one(exch: str, pair: str, session: aiohttp.ClientSession, **kwargs) -> Dict[str, Any]:
    conns: Dict[str, ExchangeL2] = {
        "binance": BinanceL2(),
        "bybit": BybitL2(),
        "kucoin": KucoinL2(),
        "deribit": DeribitL2(),
        "hyperliquid": HyperliquidL2(),
    }
    if exch not in conns:
        raise ValueError(f"Unsupported exchange: {exch}")
    try:
        return await conns[exch].fetch(session, pair, **kwargs)
    except UnsupportedInstrument as e:
        print(f"[SKIP] {exch}: {e}")
        raise

def compute_impact(book: Dict[str, Any], side: str, notional_quote: float) -> Dict[str, Any]:
    bids, asks = book["bids"], book["asks"]
    mid = compute_mid(bids, asks)
    side = side.lower()
    if side == "buy":
        avg, levels, base, q_used, full = walk_book_buy(asks, notional_quote)
    else:
        avg, levels, base, q_used, full = walk_book_sell(bids, notional_quote)
    im = impact_metrics(avg, mid, side)
    spread = (asks[0][0] - bids[0][0]) if (bids and asks) else float("nan")
    spread_bps = (spread / mid * 100 * 100) if (spread > 0 and mid > 0) else float("nan")
    return {
        "exchange": book["exchange"],
        "symbol": book["symbol"],
        "timestamp": book["timestamp"],
        "side": side,
        "requested_notional_quote": float(notional_quote),
        "avg_execution_price": avg,
        "best_bid": bids[0][0] if bids else None,
        "best_ask": asks[0][0] if asks else None,
        "market_mid_price": mid,
        "spread": spread,
        "spread_bps": spread_bps,
        "impact_pct": im["impact_pct"],
        "impact_bps": im["impact_bps"],
        "levels_touched": levels,
        "base_filled": base,
        "quote_executed": q_used,
        "fully_filled": full,
    }

def print_result(res: Dict[str, Any], dp_pct: int = 8, dp_bps: int = 6):
    ex = res["exchange"].upper()
    pct = f"{res['impact_pct']:.{dp_pct}f}" if res["impact_pct"] == res["impact_pct"] else "nan"
    bps = f"{res['impact_bps']:.{dp_bps}f}" if res["impact_bps"] == res["impact_bps"] else "nan"
    spread_bps = f"{res['spread_bps']:.{dp_bps}f}" if res["spread_bps"] == res["spread_bps"] else "nan"
    print(f"\n[{ex}] {res['symbol']} | side={res['side']} | notional={res['requested_notional_quote']}")
    print(f"  best_bid={res['best_bid']}  best_ask={res['best_ask']}  mid={res['market_mid_price']}")
    print(f"  spread={res['spread']:.8f}  ({spread_bps} bps)")
    print(f"  avg_exec={res['avg_execution_price']}  fully_filled={res['fully_filled']}  levels={res['levels_touched']}")
    print(f"  base_filled={res['base_filled']}  quote_exec={res['quote_executed']}")
    print(f"  impact = {pct}%  ({bps} bps)")

###############################################################################
# CLI
###############################################################################

async def main_async(args):
    timeout = aiohttp.ClientTimeout(total=10)
    headers = {"User-Agent": "impact/1.2"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        targets = [args.exch] if args.exch != "all" else ["binance", "bybit", "kucoin", "deribit", "hyperliquid"]
        tasks = []
        for ex in targets:
            kw = {}
            if ex == "bybit":
                kw["category"] = args.category
                kw["limit"] = args.limit if args.limit else (200 if args.category == "spot" else 500)
            elif ex == "binance":
                kw["limit"] = args.limit if args.limit else 5000
            elif ex == "deribit":
                kw["limit"] = args.limit if args.limit else 50
                kw["deribit_contract_usd"] = args.deribit_contract_usd
            tasks.append(fetch_one(ex, args.pair, session, **kw))

        books = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for ex, book in zip(targets, books):
            if isinstance(book, Exception):
                print(f"[ERROR] {ex}: {book}")
                continue
            r = compute_impact(book, args.side, args.volume)
            print_result(r, dp_pct=args.dp_pct, dp_bps=args.dp_bps)
            results.append(r)

        if args.json and results:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\nSaved JSON -> {args.json}")

def build_parser():
    p = argparse.ArgumentParser(description="Order Book Depth & Price Impact (Binance, Bybit, KuCoin, Deribit, Hyperliquid)")
    p.add_argument("pair", help="Trading pair or instrument, e.g., BTC-USDT (spot) or BTC-PERPETUAL (Deribit)")
    p.add_argument("--exch", choices=["binance", "bybit", "kucoin", "deribit", "hyperliquid", "all"], default="all")
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--volume", type=float, required=True, help="Notional in QUOTE currency (e.g., 50000 for 50k USDT)")
    p.add_argument("--category", default="spot", help="Bybit: spot|linear|inverse|option (default spot)")
    p.add_argument("--limit", type=int, default=None, help="Depth limit (Binance up to 5000; Bybit up to 500; Deribit up to ~200)")
    p.add_argument("--json", default=None, help="Write results to JSON")
    p.add_argument("--dp-pct", type=int, default=8, help="Decimal places for percent (default 8)")
    p.add_argument("--dp-bps", type=int, default=6, help="Decimal places for bps (default 6)")
    p.add_argument("--deribit-contract-usd", type=float, default=10.0,
                   help="Face value per Deribit contract in USD (default 10.0)")
    return p

def main():
    args = build_parser().parse_args()
    asyncio.run(main_async(args))

if __name__ == "__main__":
    main()
