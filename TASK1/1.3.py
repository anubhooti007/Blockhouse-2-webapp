#!/usr/bin/env python3
import asyncio
import aiohttp
import time
import json
import math
import argparse
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

# Import dual-source Binance helper
from binance_dual_source import binance_dual

HOURS_PER_YEAR = 24 * 365


# Shared helpers
def now_ms() -> int:
    return int(time.time() * 1000)

def fmt_utc(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None

def fmt_countdown(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        delta = (int(ms) - now_ms()) // 1000
        if delta < 0:
            return "0h 0m 0s"  # Funding time has passed
        h, r = divmod(delta, 3600)
        m, s = divmod(r, 60)
        return f"{int(h)}h {int(m)}m {int(s)}s"
    except Exception:
        return None

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def to_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def annualize(rate_per_period: float, period_hours: float, mode: str = "effective") -> float:
    """
    Convert a per-period funding rate (decimal, e.g. 0.0001 for 1 bp) to APR.
      - mode="simple":     APR = rate * (HOURS_PER_YEAR / period_hours)
      - mode="effective":  APR = (1 + rate)^(HOURS_PER_YEAR/period_hours) - 1
    """
    # Clamp extreme rates to prevent APR explosion
    rate_per_period = clamp(rate_per_period, -0.003, 0.003)
    
    # Prevent division by zero and extreme values
    if period_hours <= 0 or period_hours > 8760:  # Max 1 year
        return float("nan")
    
    periods = HOURS_PER_YEAR / float(period_hours)
    
    # Prevent extreme APR calculations
    if periods > 100000:  # Very frequent payouts lead to unrealistic APR
        return float("nan")
        
    if mode == "simple":
        result = rate_per_period * periods
        # Clamp simple APR to reasonable range
        return clamp(result, -100.0, 100.0)  # ±10,000% APR max
    try:
        if periods > 10000:  # Prevent overflow in power calculation
            return float("nan")
        result = math.pow(1.0 + rate_per_period, periods) - 1.0
        # Clamp effective APR to reasonable range
        return clamp(result, -1.0, 100.0)  # -100% to +10,000% APR max
    except (ValueError, OverflowError):
        return float("nan")

def apr_from_series(rates: List[float], period_hours: float, mode: str = "effective") -> float:
    if not rates:
        return float("nan")
    mean_r = sum(rates) / len(rates)
    return annualize(mean_r, period_hours, mode=mode)

def print_live(label: str, d: Dict[str, Any], payout_hours: float):
    print(f"\n[{label}] {d.get('symbol')}")
    print(f"  current_rate:  {d.get('current_rate')}")
    if d.get("predicted_rate") is not None:
        print(f"  predicted_rate:{d.get('predicted_rate')}")
    if d.get("predicted_estimate") is not None:
        print(f"  predicted_est: {d.get('predicted_estimate')}  (rough premium-based)")
    if d.get("next_funding_time"):
        iso = fmt_utc(d["next_funding_time"])
        cd  = fmt_countdown(d["next_funding_time"])
        print(f"  next_funding:  {d['next_funding_time']}  |  UTC: {iso}  |  in: {cd}")

    for mode in ("simple", "effective"):
        if d.get("current_rate") is not None:
            apr = annualize(d["current_rate"], payout_hours, mode=mode)
            print(f"  APR ({mode}, from current):  {apr:.6f}")
        if d.get("predicted_rate") is not None:
            aprp = annualize(d["predicted_rate"], payout_hours, mode=mode)
            print(f"  APR ({mode}, from predicted): {aprp:.6f}")
        elif d.get("predicted_estimate") is not None:
            aprp = annualize(d["predicted_estimate"], payout_hours, mode=mode)
            print(f"  APR ({mode}, from estimate):  {aprp:.6f}")

def print_history(label: str, rows: List[Dict[str, Any]], payout_hours: float):
    print(f"\n[{label} HISTORY] count={len(rows)}")
    if not rows:
        return
    for r in rows[-8:]:
        ts = r.get("fundingTime") or r.get("timePoint") or r.get("time") or r.get("ts")
        rate = r.get("fundingRate") or r.get("value")
        # Format timestamp as readable UTC time
        ts_formatted = fmt_utc(ts) if ts else "N/A"
        print(f"  {ts_formatted}: {rate}")
    vals = [to_float(r.get("fundingRate") or r.get("value")) for r in rows if to_float(r.get("fundingRate") or r.get("value")) is not None]
    if vals:
        mean_r = sum(vals) / len(vals)
        print(f"  mean_rate: {mean_r:.8f}")
        print(f"  APR(simple):   {annualize(mean_r, payout_hours, 'simple'):.6f}")
        print(f"  APR(effective):{annualize(mean_r, payout_hours, 'effective'):.6f}")

# BINANCE (USD-M Futures - Enhanced with predicted rates)

class BinanceFunding:
    @staticmethod
    def norm_symbol(s: str) -> str:
        s = s.upper().replace("-", "").replace("/", "").replace("_", "")
        if s.endswith("PERPETUAL"):
            s = s.split("PERPETUAL")[0] + "USDT"
        return s

    @classmethod
    async def live(cls, session: aiohttp.ClientSession, symbol: str) -> Dict[str, Any]:
        sym = cls.norm_symbol(symbol)
        
        # Use dual-source helper for futures API
        data = await binance_dual.fetch_json(session, sym, "/fapi/v1/premiumIndex", {"symbol": sym}, is_futures=True)
        
        last_rate = to_float(data.get("lastFundingRate"))
        next_time = data.get("nextFundingTime")
        mark = to_float(data.get("markPrice"))
        index = to_float(data.get("indexPrice"))
        pred_est = clamp((mark - index) / index, -0.01, 0.01) if (mark and index) else None
        return {
            "exchange": "binance",
            "symbol": sym,
            "current_rate": last_rate,
            "predicted_rate": None,  # Binance doesn't provide predicted rates via REST
            "predicted_estimate": pred_est,  # Keep premium-based estimate separate
            "next_funding_time": next_time
        }

    @classmethod
    async def history(cls, session: aiohttp.ClientSession, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        sym = cls.norm_symbol(symbol)
        params = {"symbol": sym, "limit": max(1, min(int(limit), 1000))}
        
        # Use dual-source helper for futures API
        data = await binance_dual.fetch_json(session, sym, "/fapi/v1/fundingRate", params, is_futures=True)
        
        rows = []
        for it in data if isinstance(data, list) else []:
            rows.append({
                "symbol": sym,
                "fundingRate": to_float(it.get("fundingRate")),
                "fundingTime": it.get("fundingTime")
            })
        return rows

# BYBIT (v5, linear)
class BybitFunding:
    BASE = "https://api.bybit.com"

    @staticmethod
    def norm_symbol(s: str) -> str:
        s = s.upper().replace("-", "").replace("/", "").replace("_", "")
        if s.endswith("PERPETUAL"):
            s = s.split("PERPETUAL")[0] + "USDT"
        return s

    @classmethod
    async def live(cls, session: aiohttp.ClientSession, symbol: str, category: str = "linear") -> Dict[str, Any]:
        sym = cls.norm_symbol(symbol)
        url = f"{cls.BASE}/v5/market/tickers"
        params = {"category": category, "symbol": sym}
        async with session.get(url, params=params) as r:
            data = await r.json()
        items = (data.get("result") or {}).get("list") or []
        cur = None; next_ts = None; pred = None
        if items:
            it = items[0]
            cur = to_float(it.get("fundingRate"))
            next_ts = it.get("nextFundingTime")
            pred = to_float(it.get("predictedFundingRate")) if "predictedFundingRate" in it else None
        return {
            "exchange": "bybit",
            "symbol": sym,
            "current_rate": cur,
            "predicted_rate": pred,
            "predicted_estimate": None,
            "next_funding_time": next_ts
        }

    @classmethod
    async def history(cls, session: aiohttp.ClientSession, symbol: str, category: str = "linear", limit: int = 200) -> List[Dict[str, Any]]:
        sym = cls.norm_symbol(symbol)
        url = f"{cls.BASE}/v5/market/funding/history"
        params = {"category": category, "symbol": sym, "limit": max(1, min(int(limit), 200))}
        async with session.get(url, params=params) as r:
            data = await r.json()
        rows = []
        for it in (data.get("result") or {}).get("list") or []:
            rows.append({
                "symbol": sym,
                "fundingRate": to_float(it.get("fundingRate")),
                "fundingTime": it.get("fundingRateTimestamp") or it.get("ts")
            })
        return rows

# DERIBIT (public, USD-quoted perps)
class DeribitFunding:
    """
    Uses Deribit public v2 methods:
      - /public/get_funding_rate_value?instrument_name=BTC-PERPETUAL
      - /public/get_funding_rate_history?instrument_name=BTC-PERPETUAL&start_timestamp=...&end_timestamp=...&count=...
      - /public/ticker?instrument_name=BTC-PERPETUAL  (for premium-based estimate)
    Docs list these exact method names in the 'Market data' section. 
    Funding interval is 8 hours (00:00/08:00/16:00 UTC) on Deribit. 
    """
    BASE = "https://www.deribit.com/api/v2"

    @staticmethod
    def norm_instrument(s: str) -> str:
        """
        Accepts BTC-USDT, BTCUSDT, BTC-PERPETUAL, ETH-PERPETUAL, etc.
        For Deribit we map to <BASE>-PERPETUAL (BTC/ETH).
        """
        s0 = s.upper().replace("/", "-").replace("_", "-")
        if "PERPETUAL" in s0:
            # normalize like BTC-PERPETUAL
            parts = s0.split("-")
            base = parts[0]
            return f"{base}-PERPETUAL"
        # otherwise infer base from start of string
        base = s0.split("-")[0]
        # strip quote if spot-like
        for q in ("USDT", "USD", "USDC"):
            if base.endswith(q):
                base = base[:-len(q)]
        if base not in ("BTC", "ETH"):
            # default to BTC if ambiguous
            base = "BTC"
        return f"{base}-PERPETUAL"

    @classmethod
    async def _get_json(cls, session: aiohttp.ClientSession, path: str, params: dict = None) -> dict:
        url = f"{cls.BASE}{path}"
        async with session.get(url, params=params or {}) as r:
            r.raise_for_status()  # Handle 4xx/5xx errors
            txt = await r.text()
            try:
                return json.loads(txt)
            except Exception:
                return await r.json()

    @staticmethod
    def _next_8h_utc(from_ms: Optional[int]) -> Optional[int]:
        """Compute next 00:00/08:00/16:00 UTC boundary >= from_ms."""
        if from_ms is None:
            return None
        dt = datetime.fromtimestamp(int(from_ms)/1000, tz=timezone.utc)
        hour = dt.hour
        next_hour = ((hour // 8) + 1) * 8
        # roll day if needed
        days_add = 0
        if next_hour >= 24:
            next_hour -= 24
            days_add = 1
        nxt = dt.replace(hour=next_hour, minute=0, second=0, microsecond=0) + \
              (datetime.timedelta(days=days_add) if days_add else datetime.timedelta())
        return int(nxt.timestamp() * 1000)

    @classmethod
    async def live(cls, session: aiohttp.ClientSession, symbol: str) -> Dict[str, Any]:
        instr = cls.norm_instrument(symbol)

        # 1) Current funding rate from ticker endpoint
        cur = None
        pred = None
        last_ts = None
        next_ts = None
        try:
            # Use ticker endpoint which has current_funding and funding_8h
            d = await cls._get_json(session, "/public/ticker",
                                    {"instrument_name": instr})
            res = d.get("result") or {}
            
            # Get current funding rate
            cur = to_float(res.get("current_funding") or res.get("funding_8h"))
            last_ts = res.get("timestamp")
            
            # Calculate premium-based prediction from mark vs index
            mark = to_float(res.get("mark_price"))
            index = to_float(res.get("index_price"))
            if mark and index:
                pred = clamp((mark - index) / index, -0.01, 0.01)
                
        except Exception:
            pass

        # Note: pred is already calculated above from mark/index in ticker

        # 3) If next funding not provided, derive from server time (8h cadence)
        if not next_ts:
            try:
                td = await cls._get_json(session, "/public/get_time")
                srv = td.get("result")
                if isinstance(srv, (int, float)):
                    # Find next 8h boundary from server time
                    # (simple integer math, avoids timedelta import)
                    ms = int(srv)
                    # compute hours since epoch in UTC, then the next multiple of 8
                    h = ms // (3600 * 1000)
                    next_h = (h // 8 + 1) * 8
                    next_ts = next_h * 3600 * 1000
            except Exception:
                next_ts = None

        return {
            "exchange": "deribit",
            "symbol": instr,
            "current_rate": cur,
            "predicted_rate": pred,  # Premium-based prediction
            "predicted_estimate": None,  # Keep this clear since we use predicted_rate
            "next_funding_time": next_ts
        }

    @classmethod
    async def history(cls, session: aiohttp.ClientSession, symbol: str, limit: int = 200) -> List[Dict[str, Any]]:
        instr = cls.norm_instrument(symbol)
        # Use a 30-day back window by default; Deribit supports start/end & count.
        end_ms = now_ms()
        start_ms = end_ms - 30 * 24 * 3600 * 1000
        try:
            d = await cls._get_json(
                session,
                "/public/get_funding_rate_history",
                {"instrument_name": instr, "start_timestamp": start_ms, "end_timestamp": end_ms, "count": int(limit)}
            )
        except Exception:
            d = {}
        rows: List[Dict[str, Any]] = []
        for it in (d.get("result") or d.get("data") or []):
            rows.append({
                "symbol": instr,
                "fundingRate": to_float(it.get("funding_rate") or it.get("value")),
                "fundingTime": it.get("timestamp") or it.get("time") or it.get("ts")
            })
        return rows

# KUCOIN FUTURES 
class KucoinFuturesFunding:
    BASE = "https://api-futures.kucoin.com"
    _sym_cache: Dict[str, str] = {}  # user_input -> resolved contract

    @staticmethod
    def _normalize_hint(s: str) -> Tuple[str, str]:
        """
        Turn user input into (base_hint, quote_hint) for discovery.
        BTC -> XBT, quote default USDT.
        """
        s0 = s.upper().replace("/", "").replace("-", "").replace("_", "")
        base = s0
        quote = "USDT"
        if s0.endswith("PERPETUAL"):
            base = s0[:-len("PERPETUAL")]
        elif s0.endswith("USDT"):
            base = s0[:-4]
        elif s0.endswith("USD"):
            base = s0[:-3]
            quote = "USD"
        # KuCoin uses XBT, not BTC
        if base == "BTC":
            base = "XBT"
        return base, quote

    @classmethod
    async def _get_json(cls, session: aiohttp.ClientSession, path: str, params: dict = None) -> dict:
        url = f"{cls.BASE}{path}"
        async with session.get(url, params=params or {}) as r:
            r.raise_for_status()  # Handle 4xx/5xx errors
            txt = await r.text()
            try:
                return json.loads(txt)
            except Exception:
                return await r.json()

    @classmethod
    async def _discover_symbol(cls, session: aiohttp.ClientSession, user_input: str) -> str:
        """
        Map 'BTC-USDT' / 'BTCUSDT' / 'BTC-PERPETUAL' -> actual KuCoin contract (e.g., XBTUSDTM).
        Caches result to avoid repeated discovery calls.
        """
        if user_input in cls._sym_cache:
            return cls._sym_cache[user_input]

        base_hint, quote_hint = cls._normalize_hint(user_input)

        # Fast path: common contracts we know
        if base_hint == "XBT" and quote_hint == "USDT":
            sym = "XBTUSDTM"
            cls._sym_cache[user_input] = sym
            print(f"[KUCOIN] Resolved {user_input} -> {sym}")
            return sym

        # Scan active contracts and pick a perpetual matching base/quote
        try:
            d = await cls._get_json(session, "/api/v1/contracts/active")
            arr = d.get("data") or d.get("items") or []
            # Prefer USDT-margined perpetual if multiple match
            candidates = []
            for it in arr:
                if not it.get("isActive", True):
                    continue
                if not it.get("isPerpetual", True):
                    continue
                b = (it.get("baseCurrency") or "").upper()
                q = (it.get("quoteCurrency") or "").upper()
                if b == base_hint and q == quote_hint:
                    candidates.append(it.get("symbol"))
            if candidates:
                sym = candidates[0]
                cls._sym_cache[user_input] = sym
                print(f"[KUCOIN] Resolved {user_input} -> {sym}")
                return sym
        except Exception:
            pass

        # Fallback guess
        sym = f"{base_hint}{quote_hint}M"
        cls._sym_cache[user_input] = sym
        print(f"[KUCOIN] Resolved {user_input} -> {sym} (fallback)")
        return sym

    @classmethod
    async def live(cls, session: aiohttp.ClientSession, symbol: str) -> Dict[str, Any]:
        # 1) discover actual contract code
        sym = await cls._discover_symbol(session, symbol)

        live_rate: Optional[float] = None
        next_ts: Optional[int] = None
        last_time: Optional[int] = None

        # ---- (A) funding-rate (history/latest) ----
        try:
            d1 = await cls._get_json(session, "/api/v1/funding-rate", {"symbol": sym})
            data1 = d1.get("data")
            if isinstance(data1, dict):
                live_rate = to_float(data1.get("value") or data1.get("fundingRate"))
                last_time = data1.get("timePoint")
                next_ts = data1.get("nextFundingTime") or next_ts
            elif isinstance(data1, list) and data1:
                last = data1[-1]
                live_rate = to_float(last.get("value") or last.get("fundingRate"))
                last_time = last.get("timePoint")
                next_ts = last.get("nextFundingTime") or next_ts
        except Exception:
            pass

        # ---- (B) contracts/active (single row) ----
        if live_rate is None or next_ts is None:
            try:
                d2 = await cls._get_json(session, "/api/v1/contracts/active")
                arr = d2.get("data") or d2.get("items") or []
                for it in arr:
                    if it.get("symbol") == sym:
                        live_rate = (live_rate if live_rate is not None
                                     else to_float(it.get("fundingFeeRate") or it.get("fundingRate") or it.get("fundingRateValue")))
                        next_ts = next_ts or it.get("nextFundingTime")
                        break
            except Exception:
                pass

        # ---- (C) contracts/{symbol} ----
        if live_rate is None or next_ts is None:
            try:
                d3 = await cls._get_json(session, f"/api/v1/contracts/{sym}")
                it = d3.get("data") or {}
                live_rate = (live_rate if live_rate is not None
                             else to_float(it.get("fundingFeeRate") or it.get("fundingRate") or it.get("fundingRateValue")))
                next_ts = next_ts or it.get("nextFundingTime")
            except Exception:
                pass

        # infer next funding from last_time if still missing
        if next_ts is None and last_time:
            next_ts = int(last_time) + 8 * 3600 * 1000

        # premium-based estimate
        pred_est = None
        try:
            d4 = await cls._get_json(session, "/api/v1/premium/query", {"symbol": sym})
            dp = d4.get("data") or {}
            mark = to_float(dp.get("markPrice") or dp.get("markPriceValue"))
            index = to_float(dp.get("indexPrice") or dp.get("indexPriceValue"))
            if mark and index:
                pred_est = clamp((mark - index) / index, -0.01, 0.01)
        except Exception:
            pass

        return {
            "exchange": "kucoin_futures",
            "symbol": sym,
            "current_rate": live_rate,
            "predicted_rate": None,  # KuCoin doesn't provide predicted rates via REST
            "predicted_estimate": pred_est,  # Keep premium-based estimate separate
            "next_funding_time": next_ts
        }

    @classmethod
    async def history(cls, session: aiohttp.ClientSession, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        sym = await cls._discover_symbol(session, symbol)
        d = await cls._get_json(session, "/api/v1/funding-rate", {"symbol": sym})
        rows: List[Dict[str, Any]] = []
        payload = d.get("data")
        if isinstance(payload, dict):
            payload = [payload]
        for it in (payload or [])[-limit:]:
            rows.append({
                "symbol": sym,
                "fundingRate": to_float(it.get("value") or it.get("fundingRate")),
                "fundingTime": it.get("timePoint") or it.get("ts")
            })
        return rows

# HYPERLIQUID (DEX)
class HyperliquidFunding:
    """
    Hyperliquid DEX funding rates implementation.
    Uses their info API for funding rate data.
    """
    BASE = "https://api.hyperliquid.xyz"

    @staticmethod
    def norm_coin(s: str) -> str:
        """
        Normalize symbol to Hyperliquid coin format.
        BTCUSDT -> BTC, ETHUSDT -> ETH, etc.
        """
        s0 = s.upper().replace("/", "").replace("-", "").replace("_", "")
        # Remove common quote currencies
        for quote in ("USDT", "USD", "USDC", "PERP", "PERPETUAL"):
            if s0.endswith(quote):
                s0 = s0[:-len(quote)]
        return s0

    @classmethod
    async def _get_json(cls, session: aiohttp.ClientSession, payload: dict) -> dict:
        """Make POST request to Hyperliquid info API."""
        url = f"{cls.BASE}/info"
        async with session.post(url, json=payload) as r:
            if r.status != 200:
                raise RuntimeError(f"Hyperliquid HTTP {r.status}: {await r.text()}")
            return await r.json()

    @classmethod
    async def live(cls, session: aiohttp.ClientSession, symbol: str) -> Dict[str, Any]:
        coin = cls.norm_coin(symbol)
        
        # Get funding rate info
        try:
            now = now_ms()
            payload = {
                "type": "fundingHistory",
                "coin": coin,
                "startTime": now - 48*3600*1000,   # last 48 h is plenty
                "endTime": now
            }
            data = await cls._get_json(session, payload)
            
            current_rate = None
            next_funding_time = None
            
            if isinstance(data, list) and data:
                # Get the most recent funding rate
                latest = data[-1]
                current_rate = to_float(latest.get("fundingRate"))
                next_funding_time = latest.get("time") + 3600000  # Add 1 hour for next funding
            elif isinstance(data, dict):
                current_rate = to_float(data.get("fundingRate"))
                next_funding_time = data.get("time")
                if next_funding_time:
                    next_funding_time += 3600000  # Add 1 hour for next funding
        except Exception:
            current_rate = None
            next_funding_time = None

        # Get premium-based estimate from mark/index prices
        pred_est = None
        try:
            payload = {"type": "l2Book", "coin": coin}
            book_data = await cls._get_json(session, payload)
            
            if book_data and "levels" in book_data:
                levels = book_data["levels"]
                if isinstance(levels, dict):
                    bids = levels.get("bids", [])
                    asks = levels.get("asks", [])
                elif isinstance(levels, list) and len(levels) >= 2:
                    bids = levels[0] or []
                    asks = levels[1] or []
                else:
                    bids, asks = [], []
                
                # Calculate mark price as mid of best bid/ask
                if bids and asks:
                    best_bid = float(bids[0][0]) if isinstance(bids[0], list) else float(bids[0]["px"])
                    best_ask = float(asks[0][0]) if isinstance(asks[0], list) else float(asks[0]["px"])
                    mark_price = (best_bid + best_ask) / 2
                    
                    # Get index price from meta info
                    meta_payload = {"type": "meta"}
                    meta_data = await cls._get_json(session, meta_payload)
                    
                    if meta_data and "universe" in meta_data:
                        for asset in meta_data["universe"]:
                            if asset.get("name") == coin:
                                index_price = to_float(asset.get("oraclePrice"))
                                if index_price and mark_price:
                                    pred_est = clamp((mark_price - index_price) / index_price, -0.01, 0.01)
                                break
        except Exception:
            pass

        return {
            "exchange": "hyperliquid",
            "symbol": coin,
            "current_rate": current_rate,
            "predicted_rate": None,  # Hyperliquid doesn't provide predicted rates
            "predicted_estimate": pred_est,  # Keep premium-based estimate separate
            "next_funding_time": next_funding_time
        }

    @classmethod
    async def history(cls, session: aiohttp.ClientSession, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        coin = cls.norm_coin(symbol)
        
        try:
            now = now_ms()
            payload = {
                "type": "fundingHistory",
                "coin": coin,
                "startTime": now - 7*24*3600*1000,   # last 7 days for history
                "endTime": now
            }
            data = await cls._get_json(session, payload)
            
            rows = []
            if isinstance(data, list):
                for item in data[-limit:]:
                    rows.append({
                        "symbol": coin,
                        "fundingRate": to_float(item.get("fundingRate")),
                        "fundingTime": item.get("time")
                    })
            elif isinstance(data, dict):
                rows.append({
                    "symbol": coin,
                    "fundingRate": to_float(data.get("fundingRate")),
                    "fundingTime": data.get("time")
                })
            return rows
        except Exception:
            return []

# CLI runner
CONNECTORS = {
    "binance": BinanceFunding,
    "bybit": BybitFunding,
    "deribit": DeribitFunding,
    "kucoin": KucoinFuturesFunding,
    "hyperliquid": HyperliquidFunding,
}

async def do_live(exchs: List[str], sym: str, period_hours: float):
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "funding/1.1"}) as s:
        tasks = []
        for e in exchs:
            if e == "binance":
                tasks.append(CONNECTORS[e].live(s, sym))
            elif e == "bybit":
                tasks.append(CONNECTORS[e].live(s, sym, category="linear"))
            elif e == "hyperliquid":
                tasks.append(CONNECTORS[e].live(s, sym))
            else:
                tasks.append(CONNECTORS[e].live(s, sym))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for e, res in zip(exchs, results):
            if isinstance(res, Exception):
                print(f"[ERROR] {e}: {res}")
                continue
            print_live(e, res, payout_hours=period_hours)

async def do_history(exchs: List[str], sym: str, period_hours: float, limit: int):
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "funding/1.1"}) as s:
        tasks = []
        for e in exchs:
            if e == "binance":
                tasks.append(CONNECTORS[e].history(s, sym, limit=limit))
            elif e == "bybit":
                tasks.append(CONNECTORS[e].history(s, sym, category="linear", limit=limit))
            elif e == "hyperliquid":
                tasks.append(CONNECTORS[e].history(s, sym, limit=limit))
            else:
                tasks.append(CONNECTORS[e].history(s, sym, limit=limit))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for e, rows in zip(exchs, results):
            if isinstance(rows, Exception):
                print(f"[ERROR] {e}: {rows}")
                continue
            print_history(e, rows, payout_hours=period_hours)

def main():
    ap = argparse.ArgumentParser(description="Funding rates (live, predicted, history) + APR helper for Binance / Bybit / Deribit / KuCoin Futures / Hyperliquid")
    ap.add_argument("symbol", help="e.g., BTC-USDT, BTCUSDT, or BTC-PERPETUAL")
    ap.add_argument("--exch", choices=["binance", "bybit", "deribit", "kucoin", "hyperliquid", "all"], default="all")
    ap.add_argument("--history", action="store_true", help="Fetch historical funding instead of live/predicted")
    ap.add_argument("--limit", type=int, default=100, help="Rows for history (where supported)")
    ap.add_argument("--period-hours", type=float, default=8.0, help="Funding payout interval in hours (8/4/1)")
    args = ap.parse_args()

    targets = ["binance", "bybit", "deribit", "kucoin", "hyperliquid"] if args.exch == "all" else [args.exch]

    if args.history:
        asyncio.run(do_history(targets, args.symbol, args.period_hours, args.limit))
    else:
        asyncio.run(do_live(targets, args.symbol, args.period_hours))

if __name__ == "__main__":
    main()
