#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task 2 – Trade Execution & Order Management (Binance + Bybit + Deribit)

Features:
  Universal Symbol Mapping - Accept any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)
  Multi-Exchange Support - Binance, Bybit, Deribit (spot & perpetuals)
  Time Synchronization - Auto-sync with exchange server time
  Performance Testing - Stress test with accurate reporting
  Position Monitoring - Real-time PnL tracking

Subcommands:
  place      -> create LIMIT or MARKET orders and print the orderId
  cancel     -> cancel by orderId / clientOrderId (orderLinkId on Bybit)
  status     -> fetch order status
  perftest   -> stress test (200 orders in 5 minutes by default)
  monitor    -> Position & PnL snapshot from filled orders
  symbol-test -> Test symbol mapping for any format
  debug-mark -> Test if mark prices are changing in real-time

Environment:
  # Binance
  BINANCE_API_KEY, BINANCE_API_SECRET
  # Bybit  
  BYBIT_API_KEY, BYBIT_API_SECRET
  # Deribit
  DERIBIT_CLIENT_ID, DERIBIT_CLIENT_SECRET
  # KuCoin
  KUCOIN_API_KEY, KUCOIN_API_SECRET, KUCOIN_PASSPHRASE
  # BitMart
  BITMART_API_KEY, BITMART_API_SECRET, BITMART_MEMO
  # OKX
  OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE

Examples:
  # Any symbol format works!
  python bro.py --exch binance --testnet place BTCUSDT --side BUY --type MARKET --quote 10
  python bro.py --exch binance --testnet place BTC-USDT --side BUY --type LIMIT --qty 0.00021 --price 50000
  python bro.py --exch bybit --testnet place BTC/USDT --side SELL --type LIMIT --qty 0.00021 --price 120000
  python bro.py --exch deribit --testnet place BTCUSDT --side BUY --type LIMIT --qty 5 --price 50000
  
  # Test symbol mapping
  python bro.py symbol-test BTCUSDT
  python bro.py symbol-test BTC-USDT
  python bro.py symbol-test BTC/USDT
"""
import os, time, hmac, hashlib, json, urllib.parse, random, base64
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal, ROUND_DOWN
import requests
from dotenv import load_dotenv
import argparse

# Universal Symbol Mapper
from dataclasses import dataclass
import re

_STABLES = {"USD", "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI"}
# Canonicalization: all stables -> "USD"
def _canon_quote(q: str) -> str:
    q = q.upper()
    return "USD" if q in _STABLES else q

# Base aliases (extend as needed)
_BASE_ALIASES = {
    "XBT": "BTC",
    "WBTC": "BTC",   # optional
    "WETH": "ETH",   # optional
}

# Known symbols that legitimately start with a digit (so we don't treat the digit as a multiplier)
_NUMERIC_BASE_WHITELIST = {"1INCH", "1SOL", "1ECO", "2CRZ"}  

# Quotes we try to match when the symbol is "squashed" (e.g., BTCUSDT)
_QUOTES_ORDERED = ["USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USD", "BTC", "ETH", "EUR", "TRY"]

@dataclass
class SymbolInfo:
    raw: str
    base: str
    quote: str
    canonical: str         
    is_perp: bool
    multiplier: int        # e.g. 1000 for "1000BONK", else 1
    vendor: Dict[str, str] # keys: binance_spot, binance_perp, bybit_spot, bybit_perp, kucoin_spot, kucoin_perp, deribit_perp

class UniversalSymbolMapper:
    """
    Universal symbol <-> exchange specific mapping utility.

    Canonical format used here:  BASE/QUOTE (QUOTE may be 'USD' after stablecoin folding).
    """

    @staticmethod
    def _normalize_separators(s: str) -> str:
        return s.upper().replace(" ", "").replace("_", "-").replace("/", "-")

    @staticmethod
    def _strip_perp_tokens(s: str) -> Tuple[str, bool]:
        """Return (s_without_perp_hint, is_perp) for obvious perp markers."""
        is_perp = False
        if "PERPETUAL" in s or "PERP" in s:
            is_perp = True
            s = s.replace("-PERPETUAL", "").replace("PERPETUAL", "")
            s = s.replace("-PERP", "").replace("PERP", "")
        # KuCoin linear perp suffix
        if s.endswith("USDTM"):
            is_perp = True
            s = s[:-1]  # remove trailing 'M' (…USDTM -> …USDT)
        return s, is_perp

    @staticmethod
    def _extract_multiplier(base: str) -> Tuple[str, int]:
        """
        Detect "1000BONK" style tickers. If a leading integer of >=3 digits exists and
        the remainder isn't a known numeric ticker (1INCH), treat it as multiplier.
        """
        m = re.match(r"^(\d{3,})([A-Z0-9]+)$", base)
        if not m:
            return base, 1
        digits, rem = m.group(1), m.group(2)
        if rem in _NUMERIC_BASE_WHITELIST:
            return base, 1
        return rem, int(digits)

    @staticmethod
    def _desquash(base_plus_quote: str) -> Tuple[str, str]:
        """Split a squashed symbol like BTCUSDT into (base, quote) by matching known quotes."""
        for q in _QUOTES_ORDERED:
            if base_plus_quote.endswith(q) and len(base_plus_quote) > len(q):
                return base_plus_quote[:-len(q)], q
        # Fallback: if we can't split, treat entire string as base and quote=USD
        return base_plus_quote, "USD"

    def parse(self, raw_symbol: str, exchange: Optional[str] = None) -> SymbolInfo:
        """
        Parse any exchange's symbol into a SymbolInfo (canonical, multiplier, is_perp).
        """
        raw = raw_symbol
        s = self._normalize_separators(raw_symbol)  # upper + "-" separators

        # Handle explicit perp tokens and KuCoin's USDTM
        s, is_perp_hint = self._strip_perp_tokens(s)

        base, quote = None, None

        if "-" in s:
            parts = [p for p in s.split("-") if p]
            if len(parts) == 1:
                base = parts[0]
                quote = "USD"
            elif len(parts) >= 2:
                base, quote = parts[0], parts[1]
        else:
            # No delimiter (e.g., BTCUSDT or XBTUSDTM already handled)
            base, quote = self._desquash(s)

        # Multiplier handling (1000BONK)
        base, multiplier = self._extract_multiplier(base)

        # Base aliases
        base = _BASE_ALIASES.get(base, base)

        # Final is_perp decision:
        is_perp = bool(is_perp_hint or "PERP" in s)

        # Canonical quote folding
        quote = _canon_quote(quote)

        canonical = f"{base}/{quote}"

        vendor = self._vendors(base, quote, is_perp)
        return SymbolInfo(
            raw=raw,
            base=base,
            quote=quote,
            canonical=canonical,
            is_perp=is_perp,
            multiplier=multiplier,
            vendor=vendor
        )

    # ---------- Emit symbols for each venue ----------
    def to_exchange_symbol(
        self, base: str, quote: str, exchange: str, product: str = "spot"
    ) -> str:
        base = _BASE_ALIASES.get(base.upper(), base.upper())
        quote = _canon_quote(quote)
        # choose a default stable for venues that want a specific code
        default_stable = "USDT"

        ex = exchange.lower()
        prod = product.lower()
        if ex == "binance":
            if prod == "spot":
                q = default_stable if quote == "USD" else quote
                return f"{base}{q}"
            elif prod == "perp":
                # USDⓈ-M uses same "BTCUSDT"
                return f"{base}{default_stable if quote == 'USD' else quote}"
        if ex == "bybit":
            if prod == "spot":
                q = default_stable if quote == "USD" else quote
                return f"{base}{q}"
            elif prod == "perp":
                return f"{base}{default_stable if quote == 'USD' else quote}"
        if ex == "kucoin":
            if prod == "spot":
                q = default_stable if quote == "USD" else quote
                return f"{base}-{q}"
            elif prod == "perp":
                # KuCoin perps: XBTUSDTM etc.
                b = "XBT" if base == "BTC" else base
                return f"{b}{default_stable}M" if quote == "USD" else f"{b}{quote}M"
        if ex == "deribit":
            # Perpetual naming ignores quote
            return f"{base}-PERPETUAL"
        if ex == "bitmart":
            # BitMart uses underscore format: BTC_USDT
            q = default_stable if quote == "USD" else quote
            return f"{base}_{q}"
        if ex == "okx":
            # OKX uses hyphen format: BTC-USDT
            q = default_stable if quote == "USD" else quote
            return f"{base}-{q}"
        # Fallback: canonical
        return f"{base}/{quote}"

    def _vendors(self, base: str, quote: str, is_perp: bool) -> Dict[str, str]:
        return {
            "binance_spot": self.to_exchange_symbol(base, quote, "binance", "spot"),
            "binance_perp": self.to_exchange_symbol(base, quote, "binance", "perp"),
            "bybit_spot":   self.to_exchange_symbol(base, quote, "bybit",   "spot"),
            "bybit_perp":   self.to_exchange_symbol(base, quote, "bybit",   "perp"),
            "kucoin_spot":  self.to_exchange_symbol(base, quote, "kucoin",  "spot"),
            "kucoin_perp":  self.to_exchange_symbol(base, quote, "kucoin",  "perp"),
            "deribit_perp": self.to_exchange_symbol(base, quote, "deribit", "perp"),
            "bitmart_spot": self.to_exchange_symbol(base, quote, "bitmart", "spot"),
            "okx_spot":     self.to_exchange_symbol(base, quote, "okx",     "spot"),
        }

# Global mapper instance
symbol_mapper = UniversalSymbolMapper()

# ---------- Decimal helpers ----------
def D(x) -> Decimal:
    return Decimal(str(x))

def floor_to_step(value: float, step: str | float) -> float:
    v = D(value); s = D(step)
    if s == 0: return float(v)
    q = (v / s).to_integral_value(rounding=ROUND_DOWN)
    return float(q * s)

def ceil_to_step(value: float, step: str | float) -> float:
    v = D(value); s = D(step)
    if s == 0: return float(v)
    q = (v / s).to_integral_value(rounding=ROUND_DOWN)
    if q * s < v: q += 1
    return float(q * s)

def fmt(x: float) -> str:
    return format(Decimal(str(x)).normalize(), 'f')

# Binance
class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True, recv_window: int = 5000):
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self.base = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key, "User-Agent": "task2/1.1"})
        self.time_offset_ms = 0
        self.sync_time()

    def server_time(self) -> int:
        r = self.session.get(self.base + "/api/v3/time", timeout=8)
        r.raise_for_status()
        return int(r.json()["serverTime"])

    def sync_time(self):
        try:
            st = self.server_time()
            self.time_offset_ms = st - int(time.time() * 1000)
        except Exception:
            self.time_offset_ms = 0

    def _ts(self) -> int:
        return int(time.time() * 1000) + self.time_offset_ms

    def _signed(self, method: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params)
        params["timestamp"] = self._ts()
        params["recvWindow"] = self.recv_window
        q = urllib.parse.urlencode(params, doseq=True)
        sig = hmac.new(self.api_secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{q}&signature={sig}"
        try:
            r = self.session.request(method, url, timeout=10)
            r.raise_for_status()
            return r.json() if r.text else {}
        except requests.HTTPError as e:
            code = None
            try:
                code = r.json().get("code")
            except Exception:
                pass
            if code in (-1021, -1022):
                self.sync_time()
                params["timestamp"] = self._ts()
                q = urllib.parse.urlencode(params, doseq=True)
                sig = hmac.new(self.api_secret.encode(), q.encode(), hashlib.sha256).hexdigest()
                url = f"{self.base}{path}?{q}&signature={sig}"
                r2 = self.session.request(method, url, timeout=10)
                try:
                    r2.raise_for_status()
                    return r2.json()
                except requests.HTTPError:
                    raise RuntimeError(f"HTTP {r2.status_code}: {r2.text}") from e
            raise RuntimeError(f"HTTP {r.status_code}: {r.text}") from e

    def _public(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        r = self.session.get(self.base + path, params=params or {}, timeout=10)
        r.raise_for_status()
        return r.json()

    def exchange_info(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        params = {"symbol": symbol} if symbol else {}
        return self._public("/api/v3/exchangeInfo", params)

    def book_ticker(self, symbol: str) -> Dict[str, Any]:
        return self._public("/api/v3/ticker/bookTicker", {"symbol": symbol})

    def symbol_filters(self, symbol: str) -> Dict[str, Any]:
        info = self.exchange_info(symbol)
        sym = info["symbols"][0]
        f = {x["filterType"]: x for x in sym["filters"]}
        min_notional = f.get("MIN_NOTIONAL", {}).get("minNotional") or f.get("NOTIONAL", {}).get("minNotional") or "10"
        return {
            "tickSize": f["PRICE_FILTER"]["tickSize"],
            "minPrice": f["PRICE_FILTER"]["minPrice"],
            "maxPrice": f["PRICE_FILTER"]["maxPrice"],
            "stepSize": f["LOT_SIZE"]["stepSize"],
            "minQty": f["LOT_SIZE"]["minQty"],
            "minNotional": min_notional,
            "ppbs": f.get("PERCENT_PRICE_BY_SIDE"),
        }

    def _sanitize_limit(self, symbol: str, side: str, qty: float, price: float, tif: Optional[str]) -> Tuple[float, float, str]:
        filters = self.symbol_filters(symbol)
        tick = filters["tickSize"]; step = filters["stepSize"]
        min_notional = float(filters["minNotional"])
        ppbs = filters["ppbs"]
        bt = self.book_ticker(symbol)
        bid = float(bt["bidPrice"]); ask = float(bt["askPrice"])
        ref = ask if side == "BUY" else bid
        if ppbs:
            lo = ref * float(ppbs["bidMultiplierDown"])
            hi = ref * float(ppbs["askMultiplierUp"])
        else:
            lo = float(filters["minPrice"]) if float(filters["minPrice"]) > 0 else 0.0
            hi = float(filters["maxPrice"]) if float(filters["maxPrice"]) > 0 else 1e15
        if not (lo <= price <= hi):
            raise SystemExit(f"[binance] Price {price} out of band [{lo}, {hi}]")
        price = floor_to_step(price, tick)
        qty = floor_to_step(qty, step)
        if price * qty < min_notional:
            qty = ceil_to_step(min_notional / price, step)
        return qty, price, (tif or "GTC")

    # trading
    def place_order(self, symbol: str, side: str, type_: str,
                    quantity: float | None = None, quoteOrderQty: float | None = None,
                    price: float | None = None, timeInForce: Optional[str] = None,
                    newClientOrderId: Optional[str] = None, test: bool = False) -> Dict[str, Any]:
        path = "/api/v3/order/test" if test else "/api/v3/order"
        p = {"symbol": symbol, "side": side.upper(), "type": type_.upper()}
        if newClientOrderId:
            p["newClientOrderId"] = newClientOrderId
        if p["type"] == "MARKET":
            if quoteOrderQty is not None:
                p["quoteOrderQty"] = fmt(quoteOrderQty)
            elif quantity is not None:
                step = self.symbol_filters(symbol)["stepSize"]
                p["quantity"] = fmt(floor_to_step(quantity, step))
            else:
                raise ValueError("MARKET requires --quote or --qty")
        elif p["type"] == "LIMIT":
            if quantity is None or price is None:
                raise ValueError("LIMIT requires --qty and --price")
            qty, price, tif = self._sanitize_limit(symbol, p["side"], float(quantity), float(price), timeInForce)
            p["quantity"] = fmt(qty); p["price"] = fmt(price); p["timeInForce"] = tif
        t0 = time.perf_counter()
        res = self._signed("POST", path, p)
        t1 = time.perf_counter()
        return {"order_response": res, "latency_ms": (t1 - t0) * 1000.0}

    def cancel_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        if not orderId and not origClientOrderId:
            raise ValueError("Provide orderId or origClientOrderId")
        p = {"symbol": symbol}
        if orderId: p["orderId"] = int(orderId)
        if origClientOrderId: p["origClientOrderId"] = origClientOrderId
        return self._signed("DELETE", "/api/v3/order", p)

    def get_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        if not orderId and not origClientOrderId:
            raise ValueError("Provide orderId or origClientOrderId")
        p = {"symbol": symbol}
        if orderId: p["orderId"] = int(orderId)
        if origClientOrderId: p["origClientOrderId"] = origClientOrderId
        return self._signed("GET", "/api/v3/order", p)

# Bybit (v5, SPOT)
class BybitClient:
    """
    v5 REST (spot)
      Testnet base: https://api-testnet.bybit.com
      Create  : POST /v5/order/create
      Cancel  : POST /v5/order/cancel
      Query   : GET  /v5/order/realtime
      Symbols : GET  /v5/market/instruments-info?category=spot&symbol=BTCUSDT
      Book    : GET  /v5/market/tickers?category=spot&symbol=BTCUSDT

    Auth (headers):
      X-BAPI-API-KEY, X-BAPI-TIMESTAMP, X-BAPI-RECV-WINDOW, X-BAPI-SIGN, X-BAPI-SIGN-TYPE=2
      sign = hex(HMAC_SHA256(secret, timestamp + api_key + recv_window + (query or body)))
    """
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True, recv_window: int = 5000):
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self.base = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "task2/1.1", "Content-Type": "application/json"})
        # clock skew handling
        self.time_offset_ms = 0
        self.sync_time()

    # -------- time sync ----------
    def server_time(self) -> int:
        # v5 endpoint (preferred)
        try:
            r = self.session.get(self.base + "/v5/market/time", timeout=6)
            r.raise_for_status()
            j = r.json()
            # Some deployments: {"retCode":0,"result":{"timeSecond":"...","timeNano":"..."}}
            if j.get("retCode") == 0 and j.get("result"):
                sec = j["result"].get("timeSecond")
                if sec is not None:
                    return int(sec) * 1000
        except Exception:
            pass
        # fallback older endpoint
        r = self.session.get(self.base + "/v3/public/time", timeout=6)
        r.raise_for_status()
        j = r.json()
        # {"time": 1690000000000}
        return int(j.get("time") or j.get("result", {}).get("time"))

    def sync_time(self):
        try:
            st = self.server_time()
            self.time_offset_ms = st - int(time.time() * 1000)
        except Exception:
            self.time_offset_ms = 0

    def _timestamp(self) -> str:
        return str(int(time.time() * 1000) + self.time_offset_ms)

    def _sign(self, ts: str, payload: str) -> str:
        to_sign = ts + self.api_key + str(self.recv_window) + payload
        return hmac.new(self.api_secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()

    def _req(self, method: str, path: str, params: Dict[str, Any] = None, body: Dict[str, Any] = None) -> Dict[str, Any]:
        """Auto-retries once on time/recvWindow issues (10002/10004)."""
        def do_once():
            url = self.base + path
            ts = self._timestamp()
            if method == "GET":
                q = urllib.parse.urlencode(params or {})
                if q:
                    url = f"{url}?{q}"
                payload = q
                sign = self._sign(ts, payload)
                headers = {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-SIGN": sign,
                    "X-BAPI-TIMESTAMP": ts,
                    "X-BAPI-RECV-WINDOW": str(self.recv_window),
                    "X-BAPI-SIGN-TYPE": "2",
                }
                r = self.session.get(url, headers=headers, timeout=10)
            else:
                data = json.dumps(body or {}, separators=(",", ":"))
                sign = self._sign(ts, data)
                headers = {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-SIGN": sign,
                    "X-BAPI-TIMESTAMP": ts,
                    "X-BAPI-RECV-WINDOW": str(self.recv_window),
                    "X-BAPI-SIGN-TYPE": "2",
                    "Content-Type": "application/json",
                }
                if method == "POST":
                    r = self.session.post(url, headers=headers, data=data, timeout=10)
                elif method == "DELETE":
                    r = self.session.delete(url, headers=headers, data=data, timeout=10)
                else:
                    raise ValueError("Unsupported method")
            r.raise_for_status()
            j = r.json()
            return j

        j = do_once()
        # Handle Bybit time/recvWindow errors
        if j.get("retCode") in (10002, 10004):
            # resync clock and retry once
            self.sync_time()
            j = do_once()
        if j.get("retCode") != 0:
            raise RuntimeError(f"[bybit] error {j.get('retCode')}: {j}")
        return j

    # ---------- public ----------
    def instruments(self, symbol: str) -> Dict[str, Any]:
        j = self._req("GET", "/v5/market/instruments-info", params={"category": "spot", "symbol": symbol})
        items = (j.get("result") or {}).get("list") or []
        return items[0] if items else {}

    def ticker(self, symbol: str) -> Dict[str, Any]:
        j = self._req("GET", "/v5/market/tickers", params={"category": "spot", "symbol": symbol})
        items = (j.get("result") or {}).get("list") or []
        return items[0] if items else {}

    def _filters(self, symbol: str) -> Dict[str, Any]:
        ins = self.instruments(symbol)
        pf = (ins.get("priceFilter") or {})
        lf = (ins.get("lotSizeFilter") or {})
        # Bybit exposes:
        # pf.tickSize
        # lf.basePrecision, lf.quotePrecision, lf.minOrderQty, lf.minOrderAmt
        return {
            "tickSize": pf.get("tickSize", "0.01"),
            "basePrecision": lf.get("basePrecision", "0.00000001"),
            "minOrderQty": lf.get("minOrderQty", "0"),
            "minOrderAmt": lf.get("minOrderAmt", "0"),
        }

    def _sanitize_limit(self, symbol: str, side: str, qty: float, price: float) -> Tuple[float, float]:
        f = self._filters(symbol)
        tick = f["tickSize"]; base_prec = f["basePrecision"]
        min_amt = float(f["minOrderAmt"] or 0)
        # round
        price = floor_to_step(price, tick)
        qty = floor_to_step(qty, base_prec)
        # ensure notional
        if min_amt > 0 and price * qty < min_amt:
            qty = ceil_to_step(min_amt / price, base_prec)
        return qty, price

    # ---------- trading (spot) ----------
    def place_order(self, symbol: str, side: str, type_: str,
                    quantity: float | None = None, quoteOrderQty: float | None = None,
                    price: float | None = None, timeInForce: Optional[str] = None,
                    newClientOrderId: Optional[str] = None, test: bool = False) -> Dict[str, Any]:
        # Bybit has no dedicated "test" endpoint; we always create real testnet orders.
        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy" if side.upper() == "BUY" else "Sell",
            "orderType": "Market" if type_.upper() == "MARKET" else "Limit",
        }
        if newClientOrderId:
            body["orderLinkId"] = newClientOrderId

        if body["orderType"] == "Market":
            if quoteOrderQty is not None:
                # Market buy by quote; Bybit v5 requires marketUnit + qty
                body["marketUnit"] = "quoteCoin"
                body["qty"] = fmt(quoteOrderQty)
            elif quantity is not None:
                body["marketUnit"] = "baseCoin"
                body["qty"] = fmt(quantity)
            else:
                raise ValueError("MARKET requires --quote or --qty")
            # Don't set timeInForce for market orders - let Bybit use default behavior
        else:  # Limit
            if quantity is None or price is None:
                raise ValueError("LIMIT requires --qty and --price")
            qty, pr = self._sanitize_limit(symbol, side.upper(), float(quantity), float(price))
            body["qty"] = fmt(qty)
            body["price"] = fmt(pr)
            body["timeInForce"] = timeInForce or "GTC"

        t0 = time.perf_counter()
        j = self._req("POST", "/v5/order/create", body=body)
        t1 = time.perf_counter()
        res = (j.get("result") or {})
        # Normalize similar shape to Binance for CLI print
        out = {
            "order_response": {
                "symbol": symbol,
                "orderId": res.get("orderId"),
                "clientOrderId": res.get("orderLinkId"),
                "type": body["orderType"].upper(),
                "side": side.upper(),
                "status": res.get("orderStatus"),
            },
            "latency_ms": (t1 - t0) * 1000.0
        }
        return out

    def cancel_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        body = {"category": "spot", "symbol": symbol}
        if orderId:
            body["orderId"] = str(orderId)
        elif origClientOrderId:
            body["orderLinkId"] = origClientOrderId
        else:
            raise ValueError("Provide orderId or orderLinkId (--client-id)")
        j = self._req("POST", "/v5/order/cancel", body=body)
        return j.get("result") or {}

    def get_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        params = {"category": "spot", "symbol": symbol}
        if orderId:
            params["orderId"] = str(orderId)
        if origClientOrderId:
            params["orderLinkId"] = origClientOrderId
        j = self._req("GET", "/v5/order/realtime", params=params)
        items = (j.get("result") or {}).get("list") or []
        return items[0] if items else {}

# KuCoin (v2 REST, Spot) — NO TESTNET, actual keys required
class KucoinClient:
    """
    KuCoin v2 REST API for spot trading
    Base: https://api.kucoin.com
    Auth: KC-API-KEY, KC-API-SIGN, KC-API-TIMESTAMP, KC-API-PASSPHRASE, KC-API-KEY-VERSION=2
    """
    def __init__(self, api_key: str, api_secret: str, passphrase: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        # KuCoin has no testnet for spot trading
        self.base = "https://api.kucoin.com"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "task2/kucoin/1.0"})
        self.time_offset_ms = 0
        self.sync_time()

    def server_time(self) -> int:
        r = self.session.get(self.base + "/api/v1/timestamp", timeout=8)
        r.raise_for_status()
        return int(r.json()["data"])

    def sync_time(self):
        try:
            st = self.server_time()
            self.time_offset_ms = st - int(time.time() * 1000)
        except Exception:
            self.time_offset_ms = 0

    def _timestamp(self) -> str:
        return str(int(time.time() * 1000) + self.time_offset_ms)

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        str_to_sign = timestamp + method.upper() + path + body
        signature = hmac.new(self.api_secret.encode(), str_to_sign.encode(), hashlib.sha256)
        return signature.digest().hex()

    def _req(self, method: str, path: str, params: dict = None, body: dict = None) -> dict:
        url = self.base + path
        timestamp = self._timestamp()
        
        if method == "GET":
            query_string = urllib.parse.urlencode(params or {})
            if query_string:
                path_with_query = f"{path}?{query_string}"
                url = f"{url}?{query_string}"
            else:
                path_with_query = path
            body_str = ""
        else:
            path_with_query = path
            body_str = json.dumps(body or {}, separators=(",", ":"))

        sign = self._sign(timestamp, method, path_with_query, body_str)
        passphrase_sign = hmac.new(self.api_secret.encode(), self.passphrase.encode(), hashlib.sha256).digest().hex()

        headers = {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": sign,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-PASSPHRASE": passphrase_sign,
            "KC-API-KEY-VERSION": "2",
            "Content-Type": "application/json"
        }

        if method == "GET":
            r = self.session.get(url, headers=headers, timeout=10)
        elif method == "POST":
            r = self.session.post(url, headers=headers, data=body_str, timeout=10)
        elif method == "DELETE":
            r = self.session.delete(url, headers=headers, data=body_str, timeout=10)
        else:
            raise ValueError("Unsupported method")

        r.raise_for_status()
        j = r.json()
        if j.get("code") != "200000":
            raise RuntimeError(f"[kucoin] error {j.get('code')}: {j.get('msg')}")
        return j.get("data") or {}

    def symbols_info(self) -> dict:
        return self._req("GET", "/api/v1/symbols")

    def ticker(self, symbol: str) -> dict:
        return self._req("GET", "/api/v1/market/orderbook/level1", {"symbol": symbol})

    def place_order(self, symbol: str, side: str, type_: str,
                    quantity: float | None = None, quoteOrderQty: float | None = None,
                    price: float | None = None, timeInForce: Optional[str] = None,
                    newClientOrderId: Optional[str] = None, test: bool = False) -> Dict[str, Any]:
        
        body = {
            "clientOid": newClientOrderId or f"cli_{random.randbytes(6).hex()}",
            "symbol": symbol,
            "side": side.lower(),
            "type": "market" if type_.upper() == "MARKET" else "limit"
        }

        if body["type"] == "market":
            if quoteOrderQty is not None:
                body["funds"] = str(quoteOrderQty)
            elif quantity is not None:
                body["size"] = str(quantity)
            else:
                raise ValueError("MARKET requires --quote (funds) or --qty (size)")
        else:  # limit
            if quantity is None or price is None:
                raise ValueError("LIMIT requires --qty and --price")
            body["size"] = str(quantity)
            body["price"] = str(price)
            if timeInForce:
                body["timeInForce"] = timeInForce

        t0 = time.perf_counter()
        res = self._req("POST", "/api/v1/orders", body=body)
        t1 = time.perf_counter()

        return {
            "order_response": {
                "symbol": symbol,
                "orderId": res.get("orderId"),
                "clientOrderId": body["clientOid"],
                "type": type_.upper(),
                "side": side.upper(),
                "status": "NEW"
            },
            "latency_ms": (t1 - t0) * 1000.0
        }

    def cancel_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        if orderId:
            return self._req("DELETE", f"/api/v1/orders/{orderId}")
        elif origClientOrderId:
            return self._req("DELETE", f"/api/v1/order/client-order/{origClientOrderId}")
        else:
            raise ValueError("Provide orderId or origClientOrderId")

    def get_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        if orderId:
            return self._req("GET", f"/api/v1/orders/{orderId}")
        elif origClientOrderId:
            return self._req("GET", f"/api/v1/order/client-order/{origClientOrderId}")
        else:
            raise ValueError("Provide orderId or origClientOrderId")

# =============================================================================
# BitMart (v1 REST, Spot) — NO TESTNET, actual keys required
# =============================================================================
class BitmartClient:
    """
    BitMart v1 REST API for spot trading
    Base: https://api-cloud.bitmart.com
    Auth: X-BM-KEY, X-BM-SIGN, X-BM-TIMESTAMP
    """
    def __init__(self, api_key: str, api_secret: str, memo: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.memo = memo
        # BitMart has no testnet
        self.base = "https://api-cloud.bitmart.com"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "task2/bitmart/1.0"})

    def _timestamp(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = timestamp + "#" + self.memo + "#" + method.upper() + path + body
        return hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    def _req(self, method: str, path: str, params: dict = None, body: dict = None) -> dict:
        url = self.base + path
        timestamp = self._timestamp()
        
        if method == "GET":
            query_string = urllib.parse.urlencode(params or {})
            if query_string:
                path_with_query = f"{path}?{query_string}"
                url = f"{url}?{query_string}"
            else:
                path_with_query = path
            body_str = ""
        else:
            path_with_query = path
            body_str = json.dumps(body or {}, separators=(",", ":"))

        sign = self._sign(timestamp, method, path_with_query, body_str)

        headers = {
            "X-BM-KEY": self.api_key,
            "X-BM-SIGN": sign,
            "X-BM-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

        if method == "GET":
            r = self.session.get(url, headers=headers, timeout=10)
        elif method == "POST":
            r = self.session.post(url, headers=headers, data=body_str, timeout=10)
        elif method == "DELETE":
            r = self.session.delete(url, headers=headers, data=body_str, timeout=10)
        else:
            raise ValueError("Unsupported method")

        r.raise_for_status()
        j = r.json()
        if j.get("code") != 1000:
            raise RuntimeError(f"[bitmart] error {j.get('code')}: {j.get('message')}")
        return j.get("data") or {}

    def symbols_info(self) -> dict:
        return self._req("GET", "/spot/v1/symbols")

    def ticker(self, symbol: str) -> dict:
        return self._req("GET", "/spot/v1/ticker", {"symbol": symbol})

    def place_order(self, symbol: str, side: str, type_: str,
                    quantity: float | None = None, quoteOrderQty: float | None = None,
                    price: float | None = None, timeInForce: Optional[str] = None,
                    newClientOrderId: Optional[str] = None, test: bool = False) -> Dict[str, Any]:
        
        body = {
            "symbol": symbol,
            "side": side.lower(),
            "type": "market" if type_.upper() == "MARKET" else "limit"
        }

        if newClientOrderId:
            body["client_order_id"] = newClientOrderId

        if body["type"] == "market":
            if quoteOrderQty is not None:
                body["notional"] = str(quoteOrderQty)
            elif quantity is not None:
                body["size"] = str(quantity)
            else:
                raise ValueError("MARKET requires --quote (notional) or --qty (size)")
        else:  # limit
            if quantity is None or price is None:
                raise ValueError("LIMIT requires --qty and --price")
            body["size"] = str(quantity)
            body["price"] = str(price)

        t0 = time.perf_counter()
        res = self._req("POST", "/spot/v2/submit_order", body=body)
        t1 = time.perf_counter()

        return {
            "order_response": {
                "symbol": symbol,
                "orderId": res.get("order_id"),
                "clientOrderId": body.get("client_order_id"),
                "type": type_.upper(),
                "side": side.upper(),
                "status": "NEW"
            },
            "latency_ms": (t1 - t0) * 1000.0
        }

    def cancel_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        if orderId:
            return self._req("POST", "/spot/v3/cancel_order", {"order_id": orderId})
        elif origClientOrderId:
            return self._req("POST", "/spot/v3/cancel_order", {"client_order_id": origClientOrderId})
        else:
            raise ValueError("Provide orderId or origClientOrderId")

    def get_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        if orderId:
            return self._req("GET", "/spot/v2/order_detail", {"order_id": orderId})
        elif origClientOrderId:
            return self._req("GET", "/spot/v2/order_detail", {"client_order_id": origClientOrderId})
        else:
            raise ValueError("Provide orderId or origClientOrderId")

# OKX (v5 REST, Spot) — Geo-restricted, actual keys required
class OkxClient:
    """
    OKX v5 REST API for spot trading
    Base: https://www.okx.com
    Auth: OK-ACCESS-KEY, OK-ACCESS-SIGN, OK-ACCESS-TIMESTAMP, OK-ACCESS-PASSPHRASE
    """
    def __init__(self, api_key: str, api_secret: str, passphrase: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        # OKX testnet would be https://www.okx.com (same base, different API keys)
        self.base = "https://www.okx.com"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "task2/okx/1.0"})

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()[:-6] + "Z"

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = timestamp + method.upper() + path + body
        return base64.b64encode(hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()).decode()

    def _req(self, method: str, path: str, params: dict = None, body: dict = None) -> dict:
        url = self.base + path
        timestamp = self._timestamp()
        
        if method == "GET":
            query_string = urllib.parse.urlencode(params or {})
            if query_string:
                path_with_query = f"{path}?{query_string}"
                url = f"{url}?{query_string}"
            else:
                path_with_query = path
            body_str = ""
        else:
            path_with_query = path
            body_str = json.dumps(body or {}, separators=(",", ":"))

        sign = self._sign(timestamp, method, path_with_query, body_str)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

        if method == "GET":
            r = self.session.get(url, headers=headers, timeout=10)
        elif method == "POST":
            r = self.session.post(url, headers=headers, data=body_str, timeout=10)
        elif method == "DELETE":
            r = self.session.delete(url, headers=headers, data=body_str, timeout=10)
        else:
            raise ValueError("Unsupported method")

        r.raise_for_status()
        j = r.json()
        if j.get("code") != "0":
            raise RuntimeError(f"[okx] error {j.get('code')}: {j.get('msg')}")
        return j.get("data", [{}])[0] if j.get("data") else {}

    def instruments(self, inst_type: str = "SPOT") -> dict:
        return self._req("GET", "/api/v5/public/instruments", {"instType": inst_type})

    def ticker(self, symbol: str) -> dict:
        return self._req("GET", "/api/v5/market/ticker", {"instId": symbol})

    def place_order(self, symbol: str, side: str, type_: str,
                    quantity: float | None = None, quoteOrderQty: float | None = None,
                    price: float | None = None, timeInForce: Optional[str] = None,
                    newClientOrderId: Optional[str] = None, test: bool = False) -> Dict[str, Any]:
        
        body = {
            "instId": symbol,
            "tdMode": "cash",  # spot trading
            "side": side.lower(),
            "ordType": "market" if type_.upper() == "MARKET" else "limit"
        }

        if newClientOrderId:
            body["clOrdId"] = newClientOrderId

        if body["ordType"] == "market":
            if quoteOrderQty is not None:
                body["sz"] = str(quoteOrderQty)
                body["tgtCcy"] = "quote_ccy"
            elif quantity is not None:
                body["sz"] = str(quantity)
                body["tgtCcy"] = "base_ccy"
            else:
                raise ValueError("MARKET requires --quote or --qty")
        else:  # limit
            if quantity is None or price is None:
                raise ValueError("LIMIT requires --qty and --price")
            body["sz"] = str(quantity)
            body["px"] = str(price)

        t0 = time.perf_counter()
        res = self._req("POST", "/api/v5/trade/order", body=body)
        t1 = time.perf_counter()

        return {
            "order_response": {
                "symbol": symbol,
                "orderId": res.get("ordId"),
                "clientOrderId": body.get("clOrdId"),
                "type": type_.upper(),
                "side": side.upper(),
                "status": "NEW"
            },
            "latency_ms": (t1 - t0) * 1000.0
        }

    def cancel_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        body = {"instId": symbol}
        if orderId:
            body["ordId"] = orderId
        elif origClientOrderId:
            body["clOrdId"] = origClientOrderId
        else:
            raise ValueError("Provide orderId or origClientOrderId")
        
        return self._req("POST", "/api/v5/trade/cancel-order", body=body)

    def get_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str] = None) -> Dict[str, Any]:
        params = {"instId": symbol}
        if orderId:
            params["ordId"] = orderId
        elif origClientOrderId:
            params["clOrdId"] = origClientOrderId
        else:
            raise ValueError("Provide orderId or origClientOrderId")
        
        return self._req("GET", "/api/v5/trade/order", params=params)

# Deribit (v2 HTTP, Perpetuals)  — Testnet supported
class DeribitClient:
    """
    HTTP style v2 endpoints (they mirror JSON-RPC methods):
      Auth     : GET /api/v2/public/auth?grant_type=client_credentials&client_id=...&client_secret=...
      Ticker   : GET /api/v2/public/ticker?instrument_name=BTC-PERPETUAL
      Place    : GET /api/v2/private/buy|sell?instrument_name=...&amount=...&type=market|limit&price=...
      Cancel   : GET /api/v2/private/cancel?order_id=...
      Status   : GET /api/v2/private/get_order_state?order_id=...

    Notes:
      • Deribit doesn't have spot; we'll map symbols to BTC/ETH PERPETUALS.
      • amount is the contract amount (linear USD-quoted on testnet). We accept --quote as amount.
    """
    def __init__(self, client_id: str, client_secret: str, testnet: bool = True):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base = "https://test.deribit.com" if testnet else "https://www.deribit.com"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "task2/deribit/1.0"})
        self._token = None
        self._token_exp_ms = 0
        self._auth()

    # ---------- helpers ----------
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _auth(self):
        url = f"{self.base}/api/v2/public/auth"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        r = self.session.get(url, params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
        res = j.get("result") or {}
        self._token = res.get("access_token")
        # expires_in is seconds
        self._token_exp_ms = self._now_ms() + int(res.get("expires_in", 300)) * 1000

    def _ensure_auth(self):
        if not self._token or self._now_ms() > (self._token_exp_ms - 10_000):
            self._auth()

    def _get(self, path: str, params: dict | None = None, private: bool = False) -> dict:
        url = f"{self.base}{path}"
        headers = {}
        if private:
            self._ensure_auth()
            headers["Authorization"] = f"Bearer {self._token}"
        r = self.session.get(url, params=params or {}, headers=headers, timeout=12)

        if r.status_code != 200:
            try:
                j = r.json()
                if "error" in j:
                    raise RuntimeError(f"[deribit HTTP {r.status_code}] {j['error']}")
                raise RuntimeError(f"[deribit HTTP {r.status_code}] {j}")
            except Exception:
                raise RuntimeError(f"[deribit HTTP {r.status_code}] {r.text[:500]}")
        j = r.json()
        if j.get("error"):
            raise RuntimeError(f"[deribit] {j['error']}")
        return j.get("result") or {}

    # ---------- symbol mapping ----------
    @staticmethod
    def norm_instrument(s: str) -> str:
        s0 = s.upper().replace("/", "-").replace("_", "-")
        # permit BTCUSDT/ETHUSDT etc -> <BASE>-PERPETUAL
        if "PERPETUAL" in s0:
            base = s0.split("-")[0]
        else:
            base = s0.replace("-", "")
            for q in ("USDT", "USD", "USDC"):
                if base.endswith(q):
                    base = base[: -len(q)]
                    break
        if base not in ("BTC", "ETH"):
            # only core perps supported in this quick glue
            base = "BTC"
        return f"{base}-PERPETUAL"

    # ---------- public ----------
    def ticker(self, instrument: str) -> dict:
        instr = self.norm_instrument(instrument)
        return self._get("/api/v2/public/ticker", {"instrument_name": instr})

    # ---------- trading ----------
    def place_order(
        self, symbol: str, side: str, type_: str,
        quantity: float | None = None, quoteOrderQty: float | None = None,
        price: float | None = None, timeInForce: str | None = None,
        newClientOrderId: str | None = None, test: bool = False, reduce_only: bool = False
    ) -> dict:
        # On Deribit, we treat --quote or --qty as the same "amount" (contract amount).
        instr = self.norm_instrument(symbol)
        side_lower = "buy" if side.upper() == "BUY" else "sell"
        order_type = "market" if type_.upper() == "MARKET" else "limit"
        amount = quoteOrderQty if quoteOrderQty is not None else quantity
        if amount is None:
            raise ValueError("Deribit requires --quote or --qty (amount in contract units).")

        params = {
            "instrument_name": instr,
            "amount": int(float(amount)),  # Deribit expects integer amounts
            "type": order_type,
        }
        if order_type == "limit":
            if price is None:
                raise ValueError("LIMIT requires --price on Deribit")
            params["price"] = float(price)
            if timeInForce:
                # Deribit TIFs: "good_til_cancelled", "fill_or_kill", "immediate_or_cancel"
                tif_map = {"GTC": "good_til_cancelled", "IOC": "immediate_or_cancel", "FOK": "fill_or_kill"}
                params["time_in_force"] = tif_map.get(timeInForce, "good_til_cancelled")

        # They support client order id as 'label'
        if newClientOrderId:
            params["label"] = newClientOrderId

        # Add reduce-only flag if specified
        if reduce_only:
            params["reduce_only"] = True

        # /private/buy or /private/sell
        path = f"/api/v2/private/{side_lower}"
        t0 = time.perf_counter()
        res = self._get(path, params=params, private=True)
        t1 = time.perf_counter()
        order = res.get("order") or res  # some responses return 'order'
        out = {
            "order_response": {
                "symbol": instr,
                "orderId": str(order.get("order_id")),
                "clientOrderId": order.get("label"),
                "type": type_.upper(),
                "side": side.upper(),
                "status": order.get("order_state"),
            },
            "latency_ms": (t1 - t0) * 1000.0
        }
        return out

    def cancel_order(self, symbol: str, orderId: str | None = None, origClientOrderId: str | None = None) -> dict:
        if not orderId:
            # Deribit's cancel requires order_id; label cancel is not supported on this path.
            raise ValueError("Deribit cancel requires --order-id")
        res = self._get("/api/v2/private/cancel", {"order_id": orderId}, private=True)
        return res.get("order") or res

    def get_order(self, symbol: str, orderId: str | None = None, origClientOrderId: str | None = None) -> dict:
        if not orderId:
            raise ValueError("Deribit status requires --order-id")
        return self._get("/api/v2/private/get_order_state", {"order_id": orderId}, private=True)

    # for safe LIMIT away-from-market
    def safe_limit(self, symbol: str, side: str, away: float = 0.15) -> tuple[float, float]:
        t = self.ticker(symbol)
        bid = float(t.get("best_bid_price") or t.get("best_bid") or t.get("bid_price") or 0.0)
        ask = float(t.get("best_ask_price") or t.get("best_ask") or t.get("ask_price") or 0.0)
        ref = ask if side.upper() == "BUY" else bid
        if ref <= 0:
            # fallback constant if ticker absent
            ref = 10000.0
        price = ref * (1.0 - away) if side.upper() == "BUY" else ref * (1.0 + away)
        # amount: tiny default to keep margin small (contract USD) - must be integer
        amt = 5
        return price, amt

def make_client(exch: str, testnet: bool):
    if exch == "binance":
        key = os.getenv("BINANCE_API_KEY"); sec = os.getenv("BINANCE_API_SECRET")
        if not key or not sec:
            raise SystemExit("Set BINANCE_API_KEY and BINANCE_API_SECRET.")
        return BinanceClient(key, sec, testnet=testnet)
    elif exch == "bybit":
        key = os.getenv("BYBIT_API_KEY"); sec = os.getenv("BYBIT_API_SECRET")
        if not key or not sec:
            raise SystemExit("Set BYBIT_API_KEY and BYBIT_API_SECRET.")
        return BybitClient(key, sec, testnet=testnet)
    elif exch == "deribit":
        cid = os.getenv("DERIBIT_CLIENT_ID"); csec = os.getenv("DERIBIT_CLIENT_SECRET")
        if not cid or not csec:
            raise SystemExit("Set DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET.")
        return DeribitClient(cid, csec, testnet=testnet)
    elif exch == "kucoin":
        key = os.getenv("KUCOIN_API_KEY"); sec = os.getenv("KUCOIN_API_SECRET"); passphrase = os.getenv("KUCOIN_PASSPHRASE")
        if not key or not sec or not passphrase:
            raise SystemExit("Set KUCOIN_API_KEY, KUCOIN_API_SECRET, and KUCOIN_PASSPHRASE.")
        return KucoinClient(key, sec, passphrase, testnet=testnet)
    elif exch == "bitmart":
        key = os.getenv("BITMART_API_KEY"); sec = os.getenv("BITMART_API_SECRET"); memo = os.getenv("BITMART_MEMO")
        if not key or not sec or not memo:
            raise SystemExit("Set BITMART_API_KEY, BITMART_API_SECRET, and BITMART_MEMO.")
        return BitmartClient(key, sec, memo, testnet=testnet)
    elif exch == "okx":
        key = os.getenv("OKX_API_KEY"); sec = os.getenv("OKX_API_SECRET"); passphrase = os.getenv("OKX_PASSPHRASE")
        if not key or not sec or not passphrase:
            raise SystemExit("Set OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE.")
        return OkxClient(key, sec, passphrase, testnet=testnet)
    else:
        raise SystemExit("Unsupported exchange")

def normalize_symbol_for_exchange(raw_symbol: str, exchange: str, product: str = "spot") -> str:
    """
    Normalize any symbol format to the correct exchange-specific format.
    
    Args:
        raw_symbol: Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)
        exchange: Exchange name (binance, bybit, deribit)
        product: Product type (spot, perp)
    
    Returns:
        Exchange-specific symbol string
    """
    try:
        info = symbol_mapper.parse(raw_symbol)
        # For Deribit, always use perp since they don't have spot
        if exchange == "deribit":
            product = "perp"
        return symbol_mapper.to_exchange_symbol(info.base, info.quote, exchange, product)
    except Exception as e:
        # Fallback to old behavior for compatibility
        print(f"Warning: Symbol mapping failed for '{raw_symbol}': {e}")
        return raw_symbol.upper().replace("-", "").replace("/", "")

def cli_place(args):
    if not args.exch:
        raise SystemExit("--exch is required for place command")
    client = make_client(args.exch, args.testnet)
    symbol = normalize_symbol_for_exchange(args.symbol, args.exch, "spot")
    cid = args.client_id or f"cli_{random.randbytes(6).hex()}"
    
    # Build order parameters
    order_params = {
        "symbol": symbol,
        "side": args.side,
        "type_": args.type,
        "quantity": args.qty,
        "quoteOrderQty": args.quote,
        "price": args.price,
        "timeInForce": args.tif,
        "newClientOrderId": cid,
        "test": args.test,
    }
    
    # Only add reduce_only for Deribit
    if args.exch == "deribit" and getattr(args, 'reduce_only', False):
        order_params["reduce_only"] = True
    
    out = client.place_order(**order_params)
    print(json.dumps(out, indent=2))
    try:
        orid = out["order_response"]["orderId"]
        print(f"\nORDER ID: {orid}")
    except Exception:
        pass

def cli_cancel(args):
    if not args.exch:
        raise SystemExit("--exch is required for cancel command")
    client = make_client(args.exch, args.testnet)
    symbol = normalize_symbol_for_exchange(args.symbol, args.exch, "spot")
    out = client.cancel_order(symbol, orderId=args.order_id, origClientOrderId=args.client_id)
    print(json.dumps(out, indent=2))

def cli_status(args):
    if not args.exch:
        raise SystemExit("--exch is required for status command")
    client = make_client(args.exch, args.testnet)
    symbol = normalize_symbol_for_exchange(args.symbol, args.exch, "spot")
    out = client.get_order(symbol, orderId=args.order_id, origClientOrderId=args.client_id)
    print(json.dumps(out, indent=2))

def choose_safe_limit(exch: str, client, symbol: str, side: str, away: float = 0.15) -> Tuple[float, float]:
    # symbol is already normalized by the calling function
    if exch == "binance":
        bt = client.book_ticker(symbol)
        bid = float(bt["bidPrice"]); ask = float(bt["askPrice"])
        ref = ask if side == "BUY" else bid
        filters = client.symbol_filters(symbol)
        tick = filters["tickSize"]; step = filters["stepSize"]; min_notional = float(filters["minNotional"])
        target = ref * (1 - away) if side == "BUY" else ref * (1 + away)
        price = floor_to_step(target, tick)
        qty = ceil_to_step(min_notional / price, step)
        return price, qty
    elif exch == "bybit":
        t = client.ticker(symbol)
        bid = float(t.get("bid1Price") or t.get("bidPrice") or 0)
        ask = float(t.get("ask1Price") or t.get("askPrice") or 0)
        ref = ask if side == "BUY" else bid
        f = client._filters(symbol)
        tick = f["tickSize"]; base_prec = f["basePrecision"]; min_amt = float(f["minOrderAmt"] or 0)
        target = ref * (1 - away) if side == "BUY" else ref * (1 + away)
        price = floor_to_step(target, tick)
        qty = ceil_to_step((min_amt or 10.0) / max(price, 1e-9), base_prec)  # fallback min 10 quote
        return price, qty
    else:  # deribit
        price, amt = client.safe_limit(symbol, side, away=away)
        # qty = 'amount' contracts; return (price, qty) - Deribit expects integers
        return price, int(amt)

# Performance Test 
import random, statistics, time, json

def _percentile(arr, p):
    if not arr: return None
    arr = sorted(arr)
    k = (len(arr)-1) * (p/100.0)
    f = int(k); c = min(f+1, len(arr)-1)
    if f == c: return arr[f]
    return arr[f] + (arr[c]-arr[f]) * (k - f)

def _safe_limit_binance(client, symbol, side, away=0.15):
    bt = client.book_ticker(symbol)
    bid = float(bt["bidPrice"]); ask = float(bt["askPrice"])
    ref = ask if side == "BUY" else bid
    filters = client.symbol_filters(symbol)
    tick = filters["tickSize"]; step = filters["stepSize"]; min_notional = float(filters["minNotional"])
    target = ref * (1 - away) if side == "BUY" else ref * (1 + away)
    # round price/qty
    from decimal import Decimal as _D, ROUND_DOWN
    price = float((_D(str(target)) / _D(str(tick))).to_integral_value(rounding=ROUND_DOWN) * _D(str(tick)))
    qty   = float((_D(str(min_notional/price)) / _D(str(step))).to_integral_value(rounding=ROUND_DOWN) * _D(str(step)))
    if qty * price < min_notional:
        qty = float(((_D(str(min_notional/price)) / _D(str(step))).to_integral_value(rounding=ROUND_DOWN) + 1) * _D(str(step)))
    return price, qty

def _safe_limit_bybit(client, symbol, side, away=0.15):
    t = client.ticker(symbol)
    bid = float(t.get("bid1Price") or t.get("bidPrice") or 0)
    ask = float(t.get("ask1Price") or t.get("askPrice") or 0)
    ref = ask if side == "BUY" else bid
    f = client._filters(symbol)
    tick = f["tickSize"]; base_prec = f["basePrecision"]; min_amt = float(f["minOrderAmt"] or 0)
    from decimal import Decimal as _D, ROUND_DOWN
    target = ref * (1-away) if side == "BUY" else ref * (1+away)
    price = float((_D(str(target)) / _D(str(tick))).to_integral_value(rounding=ROUND_DOWN) * _D(str(tick)))
    if price <= 0:  # fallback
        price = float(tick)
    # ensure min notional
    qty = float((_D(str((max(min_amt, 10.0)/price))) / _D(str(base_prec))).to_integral_value(rounding=ROUND_DOWN) * _D(str(base_prec)))
    if qty * price < max(min_amt, 10.0):
        qty = float(((_D(str((max(min_amt, 10.0)/price))) / _D(str(base_prec))).to_integral_value(rounding=ROUND_DOWN) + 1) * _D(str(base_prec)))
    return price, qty

def _deribit_instr_info(client, instr):
    r = client.session.get(f"{client.base}/api/v2/public/get_instrument", params={"instrument_name": instr}, timeout=8)
    r.raise_for_status()
    j = r.json()
    if "error" in j: raise RuntimeError(j["error"])
    return j.get("result") or {}

def _safe_limit_deribit(client, symbol, side, away=0.18):
    instr = DeribitClient.norm_instrument(symbol)  # static method
    info = _deribit_instr_info(client, instr)
    tick = float(info.get("tick_size", 0.5))
    min_amt = float(info.get("min_trade_amount", 10))
    step = float(info.get("amount_step", 10))

    # mid from ticker
    t = client.session.get(f"{client.base}/api/v2/public/ticker", params={"instrument_name": instr}, timeout=8)
    t.raise_for_status()
    tj = t.json().get("result", {})
    bid = float(tj.get("best_bid_price") or tj.get("best_bid") or 0)
    ask = float(tj.get("best_ask_price") or tj.get("best_ask") or 0)
    ref = ask if side == "BUY" else bid
    target = ref * (1-away) if side == "BUY" else ref * (1+away)

    # round price and amount
    price = int(target / tick) * tick or tick
    amount = max(min_amt, step)
    amount = int((amount + step - 1) / step) * step
    return price, amount

def _choose_order_params(exch, client, symbol, i, market_quote_default=10.0):
    # symbol is already normalized by the calling function
    side = "BUY" if (i % 2 == 0) else "SELL"
    # 50/50 mix, but Deribit perf test -> prefer LIMIT (market fills instantly)
    otype = "LIMIT" if exch == "deribit" else ("LIMIT" if random.random() < 0.5 else "MARKET")

    if exch == "binance":
        if otype == "LIMIT":
            price, qty = _safe_limit_binance(client, symbol, side, away=0.18)
            return {"side": side, "type": "LIMIT", "qty": qty, "price": price}
        else:
            return {"side": side, "type": "MARKET", "quote": market_quote_default}

    if exch == "bybit":
        if otype == "LIMIT":
            price, qty = _safe_limit_bybit(client, symbol, side, away=0.18)
            return {"side": side, "type": "LIMIT", "qty": qty, "price": price}
        else:
            return {"side": side, "type": "MARKET", "quote": market_quote_default}

    if exch == "deribit":
        price, amt = _safe_limit_deribit(client, symbol, side, away=0.20)
        # Deribit uses "amount" contracts; map to qty for your place_order()
        return {"side": side, "type": "LIMIT", "qty": amt, "price": price}

    if exch in ("kucoin", "bitmart", "okx"):
        # For new exchanges, use simple LIMIT orders with basic pricing
        if otype == "LIMIT":
            # Use basic away-from-market pricing
            try:
                ticker = client.ticker(symbol) if hasattr(client, 'ticker') else {}
                if exch == "kucoin":
                    bid = float(ticker.get("bestBid", 0) or 50000)
                    ask = float(ticker.get("bestAsk", 0) or 50000)
                elif exch == "bitmart":
                    bid = float(ticker.get("best_bid", 0) or 50000)
                    ask = float(ticker.get("best_ask", 0) or 50000)
                elif exch == "okx":
                    bid = float(ticker.get("bidPx", 0) or 50000)
                    ask = float(ticker.get("askPx", 0) or 50000)
                
                ref = ask if side == "BUY" else bid
                away = 0.15
                price = ref * (1 - away) if side == "BUY" else ref * (1 + away)
                qty = market_quote_default / price  # Convert quote amount to base quantity
                return {"side": side, "type": "LIMIT", "qty": qty, "price": price}
            except Exception:
                # Fallback to fixed values
                price = 45000 if side == "BUY" else 55000
                qty = market_quote_default / price
                return {"side": side, "type": "LIMIT", "qty": qty, "price": price}
        else:
            return {"side": side, "type": "MARKET", "quote": market_quote_default}

    raise ValueError("Unknown exchange")

def cli_perftest(args):
    """Place N orders within duration seconds; cancel each immediately; print stats."""
    if not args.exch:
        raise SystemExit("--exch is required for perftest command")
    client = make_client(args.exch, args.testnet)
    symbol = normalize_symbol_for_exchange(args.symbol, args.exch, "spot")
    count = int(args.count)
    deadline = time.time() + int(args.duration)

    results = []
    placed_tried = 0
    p_ok = p_fail = c_ok = c_fail = 0
    lat_p, lat_c = [], []

    for i in range(count):
        if time.time() > deadline:
            break

        # 1) choose order params
        try:
            op = _choose_order_params(args.exch, client, symbol, i)
        except Exception as e:
            p_fail += 1
            results.append({"i": i, "choose_error": str(e)})
            continue

        # 2) place
        try:
            placed_tried += 1
            t0 = time.perf_counter()
            resp = client.place_order(
                symbol=symbol,
                side=op["side"],
                type_=op["type"],
                quantity=op.get("qty"),
                quoteOrderQty=op.get("quote"),
                price=op.get("price"),
                timeInForce="GTC",
                newClientOrderId=f"pt_{i}"
            )
            t1 = time.perf_counter()
            p_ok += 1
            lat_p.append((t1 - t0) * 1000.0)
            order_id = resp["order_response"]["orderId"]
        except Exception as e:
            p_fail += 1
            results.append({"i": i, "place_error": str(e)})
            # pace anyway
            remaining = max(0.0, deadline - time.time())
            left = max(1, count - (i + 1))
            time.sleep(min(0.01, remaining / left))
            continue

        # 3) cancel immediately
        try:
            t0 = time.perf_counter()
            client.cancel_order(symbol, orderId=order_id)
            t1 = time.perf_counter()
            c_ok += 1
            lat_c.append((t1 - t0) * 1000.0)
        except Exception as e:
            c_fail += 1
            results.append({"i": i, "cancel_error": str(e), "orderId": order_id})

        # 4) pace to finish within duration
        remaining = deadline - time.time()
        left = count - (i + 1)
        if left > 0 and remaining > 0:
            time.sleep(max(0.0, remaining / left))

    # 5) summary with accurate reporting
    skipped = count - placed_tried
    def p50(xs): 
        if not xs: return None
        xs = sorted(xs); n = len(xs); mid = (n-1)/2
        import math
        lo, hi = xs[math.floor(mid)], xs[math.ceil(mid)]
        return (lo + hi)/2
    def p95(xs):
        if not xs: return None
        import math
        xs = sorted(xs); idx = int(math.ceil(0.95*len(xs)))-1
        return xs[max(0, min(idx, len(xs)-1))]

    summary = {
        "exchange": args.exch,
        "symbol": symbol,
        "attempted": placed_tried,          # <-- actual attempts
        "placed_ok": p_ok, "placed_fail": p_fail,
        "cancel_ok": c_ok, "cancel_fail": c_fail,
        "skipped_due_to_deadline": skipped, # <-- new field
        "avg_place_ms": (sum(lat_p)/len(lat_p)) if lat_p else None,
        "avg_cancel_ms": (sum(lat_c)/len(lat_c)) if lat_c else None,
        "p50_place_ms": p50(lat_p), "p95_place_ms": p95(lat_p),
        "p50_cancel_ms": p50(lat_c), "p95_cancel_ms": p95(lat_c),
        "errors": results[-10:]  # last few errors
    }
    print(json.dumps(summary, indent=2))


# Task 3 — Position & PnL monitor
from datetime import datetime, timezone

def _iso(ms: int | str | None) -> str | None:
    try:
        ms = int(ms)
        return datetime.fromtimestamp(ms/1000, tz=timezone.utc).isoformat()
    except Exception:
        return None

def _binance_snapshot(client, symbol: str, order_id: int | None, client_id: str | None):
    """
    Returns:
      {
        connector_name, pair_name, entry_timestamp, entry_price, quantity,
        position_side, mark_price, NetPnL, NetPnL_pct
      }
    """
    # 1) order object
    od = client.get_order(symbol, orderId=order_id, origClientOrderId=client_id)
    if od.get("status") not in ("FILLED", "PARTIALLY_FILLED"):
        raise RuntimeError(f"[binance] order not filled: {od.get('status')}")
    side = od["side"].upper()
    exec_qty = float(od.get("executedQty", "0"))
    # 2) avg price from trades (myTrades is reliable)
    tr = client._signed("GET", "/api/v3/myTrades", {"symbol": symbol, "orderId": od["orderId"]})
    if not tr:
        # fallback to cummulativeQuote/execQty
        if exec_qty > 0:
            avg_px = float(od.get("cummulativeQuoteQty", "0")) / exec_qty
            et_ms = od.get("transactTime") or od.get("time")
        else:
            raise RuntimeError("[binance] no trades for filled order?")
    else:
        notional = 0.0; qty = 0.0; et_ms = tr[0].get("time")
        for t in tr:
            p = float(t["price"]); q = float(t["qty"])
            notional += p * q; qty += q
            if et_ms is None or int(t["time"]) < int(et_ms):
                et_ms = t["time"]
        avg_px = notional / qty if qty else float("nan")
        exec_qty = qty

    # 3) live mark/mid (book mid)
    bt = client.book_ticker(symbol)
    bid = float(bt["bidPrice"]); ask = float(bt["askPrice"])
    mid = (bid + ask) / 2.0

    # 4) PnL (spot logic; SELL treated as short if margin; otherwise this is leg PnL)
    if side == "BUY":
        pnl = (mid - avg_px) * exec_qty
    else:
        pnl = (avg_px - mid) * exec_qty
    denom = (avg_px * exec_qty) if (avg_px and exec_qty) else float("nan")
    pnl_pct = pnl / denom if denom and denom != 0 else float("nan")

    return {
        "connector_name": "binance",
        "pair_name": symbol,
        "entry_timestamp": _iso(et_ms),
        "entry_price": avg_px,
        "quantity": exec_qty,
        "position_side": "long" if side == "BUY" else "short",
        "mark_price": mid,
        "NetPnL": pnl,
        "NetPnL_pct": pnl_pct,
    }

def _bybit_snapshot(client, symbol: str, order_id: str | None, client_id: str | None):
    # 1) order
    od = client.get_order(symbol, orderId=order_id, origClientOrderId=client_id)
    if not od:
        raise RuntimeError("[bybit] order not found")
    st = (od.get("orderStatus") or od.get("orderStatus")) or ""
    if st.upper() not in ("FILLED", "PARTIALLY_FILLED"):
        raise RuntimeError(f"[bybit] order not filled: {st}")
    side = "BUY" if (od.get("side","").lower() == "buy") else "SELL"
    avg_px = float(od.get("avgPrice") or 0.0)
    exec_qty = float(od.get("cumExecQty") or 0.0)
    et_ms = int(od.get("createdTime") or od.get("createTime") or od.get("updatedTime") or 0)

    # 2) live tick (mid)
    tk = client.ticker(symbol)
    bid = float(tk.get("bid1Price") or tk.get("bidPrice") or 0)
    ask = float(tk.get("ask1Price") or tk.get("askPrice") or 0)
    mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("lastPrice") or 0)

    # 3) PnL
    if side == "BUY":
        pnl = (mid - avg_px) * exec_qty
    else:
        pnl = (avg_px - mid) * exec_qty
    denom = (avg_px * exec_qty) if (avg_px and exec_qty) else float("nan")
    pnl_pct = pnl / denom if denom and denom != 0 else float("nan")

    return {
        "connector_name": "bybit",
        "pair_name": symbol,
        "entry_timestamp": _iso(et_ms),
        "entry_price": avg_px,
        "quantity": exec_qty,
        "position_side": "long" if side == "BUY" else "short",
        "mark_price": mid,
        "NetPnL": pnl,
        "NetPnL_pct": pnl_pct,
    }

def _deribit_snapshot(client, symbol: str, order_id: str | None, client_id: str | None):
    """
    Deribit perps are **inverse**. For BTC-PERPETUAL the contract size is typically 10 USD.
    PnL (in BTC) = contract_size * amount * (1/entry - 1/mark) for BUY (long)
                   = contract_size * amount * (1/mark - 1/entry) for SELL (short)
    We also return PnL in USD using the index (mark) price.
    """
    instr = DeribitClient.norm_instrument(symbol)

    # 1) order state - use the client's _get method for proper auth and error handling
    params = {"order_id": order_id} if order_id else {"label": client_id}
    try:
        od = client._get("/api/v2/private/get_order_state", params=params, private=True)
    except Exception as e:
        raise RuntimeError(f"[deribit] Failed to get order state: {e}")
    
    if (od.get("order_state") or "").lower() not in ("filled", "open", "partially_filled"):
        raise RuntimeError(f"[deribit] order not found/invalid state: {od.get('order_state')}")

    direction = od.get("direction","")
    side = "BUY" if direction.lower() == "buy" else "SELL"
    avg_px = float(od.get("average_price") or 0.0)
    amt    = float(od.get("filled_amount") or od.get("amount") or 0.0)
    et_ms  = int(od.get("creation_timestamp") or od.get("last_update_timestamp") or 0)

    # 2) instrument info (contract_size)
    try:
        info = client._get("/api/v2/public/get_instrument", {"instrument_name": instr})
    except Exception as e:
        raise RuntimeError(f"[deribit] Failed to get instrument info: {e}")
    csz  = float(info.get("contract_size") or 10.0)  # USD per contract

    # 3) mark / index
    try:
        tkr = client._get("/api/v2/public/ticker", {"instrument_name": instr})
    except Exception as e:
        raise RuntimeError(f"[deribit] Failed to get ticker: {e}")
    mark = float(tkr.get("mark_price") or tkr.get("last_price") or 0.0)
    index = float(tkr.get("index_price") or mark)

    # 4) PnL inverse (in BTC), then USD
    if avg_px <= 0 or mark <= 0 or amt <= 0:
        pnl_btc = 0.0
    else:
        if side == "BUY":
            pnl_btc = csz * amt * (1.0/avg_px - 1.0/mark)
        else:
            pnl_btc = csz * amt * (1.0/mark - 1.0/avg_px)
    pnl_usd = pnl_btc * index
    notional_usd = (csz * amt)  # roughly the USD exposure
    pnl_pct = (pnl_usd / notional_usd) if notional_usd else float("nan")

    return {
        "connector_name": "deribit",
        "pair_name": instr,
        "entry_timestamp": _iso(et_ms),
        "entry_price": avg_px,
        "quantity": amt,
        "position_side": "long" if side == "BUY" else "short",
        "mark_price": mark,
        "NetPnL": pnl_usd,            # in USD
        "NetPnL_pct": pnl_pct,
        "NetPnL_underlying": pnl_btc  # in BTC/ETH
    }

def _kucoin_snapshot(client, symbol: str, order_id: str | None, client_id: str | None):
    """KuCoin position snapshot"""
    # 1) order
    od = client.get_order(symbol, orderId=order_id, origClientOrderId=client_id)
    if not od:
        raise RuntimeError("[kucoin] order not found")
    
    side = od.get("side", "").upper()
    avg_px = float(od.get("dealPrice") or od.get("price") or 0.0)
    exec_qty = float(od.get("dealSize") or od.get("size") or 0.0)
    et_ms = int(od.get("createdAt") or 0)

    # 2) live tick
    tk = client.ticker(symbol)
    bid = float(tk.get("bestBid", 0) or 0)
    ask = float(tk.get("bestAsk", 0) or 0)
    mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("price") or 0)

    # 3) PnL
    if side == "BUY":
        pnl = (mid - avg_px) * exec_qty
    else:
        pnl = (avg_px - mid) * exec_qty
    denom = (avg_px * exec_qty) if (avg_px and exec_qty) else float("nan")
    pnl_pct = pnl / denom if denom and denom != 0 else float("nan")

    return {
        "connector_name": "kucoin",
        "pair_name": symbol,
        "entry_timestamp": _iso(et_ms),
        "entry_price": avg_px,
        "quantity": exec_qty,
        "position_side": "long" if side == "BUY" else "short",
        "mark_price": mid,
        "NetPnL": pnl,
        "NetPnL_pct": pnl_pct,
    }

def _bitmart_snapshot(client, symbol: str, order_id: str | None, client_id: str | None):
    """BitMart position snapshot"""
    # 1) order
    od = client.get_order(symbol, orderId=order_id, origClientOrderId=client_id)
    if not od:
        raise RuntimeError("[bitmart] order not found")
    
    side = od.get("side", "").upper()
    avg_px = float(od.get("price") or 0.0)
    exec_qty = float(od.get("filled_size") or od.get("size") or 0.0)
    et_ms = int(od.get("create_time") or 0)

    # 2) live tick
    tk = client.ticker(symbol)
    bid = float(tk.get("best_bid", 0) or 0)
    ask = float(tk.get("best_ask", 0) or 0)
    mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("last_price") or 0)

    # 3) PnL
    if side == "BUY":
        pnl = (mid - avg_px) * exec_qty
    else:
        pnl = (avg_px - mid) * exec_qty
    denom = (avg_px * exec_qty) if (avg_px and exec_qty) else float("nan")
    pnl_pct = pnl / denom if denom and denom != 0 else float("nan")

    return {
        "connector_name": "bitmart",
        "pair_name": symbol,
        "entry_timestamp": _iso(et_ms),
        "entry_price": avg_px,
        "quantity": exec_qty,
        "position_side": "long" if side == "BUY" else "short",
        "mark_price": mid,
        "NetPnL": pnl,
        "NetPnL_pct": pnl_pct,
    }

def _okx_snapshot(client, symbol: str, order_id: str | None, client_id: str | None):
    """OKX position snapshot"""
    # 1) order
    od = client.get_order(symbol, orderId=order_id, origClientOrderId=client_id)
    if not od:
        raise RuntimeError("[okx] order not found")
    
    side = od.get("side", "").upper()
    avg_px = float(od.get("avgPx") or od.get("px") or 0.0)
    exec_qty = float(od.get("accFillSz") or od.get("sz") or 0.0)
    et_ms = int(od.get("cTime") or od.get("uTime") or 0)

    # 2) live tick
    tk = client.ticker(symbol)
    bid = float(tk.get("bidPx", 0) or 0)
    ask = float(tk.get("askPx", 0) or 0)
    mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("last") or 0)

    # 3) PnL
    if side == "BUY":
        pnl = (mid - avg_px) * exec_qty
    else:
        pnl = (avg_px - mid) * exec_qty
    denom = (avg_px * exec_qty) if (avg_px and exec_qty) else float("nan")
    pnl_pct = pnl / denom if denom and denom != 0 else float("nan")

    return {
        "connector_name": "okx",
        "pair_name": symbol,
        "entry_timestamp": _iso(et_ms),
        "entry_price": avg_px,
        "quantity": exec_qty,
        "position_side": "long" if side == "BUY" else "short",
        "mark_price": mid,
        "NetPnL": pnl,
        "NetPnL_pct": pnl_pct,
    }

def get_position_snapshot(exch: str, client, symbol: str, order_id: str | int | None, client_id: str | None):
    if exch == "binance":
        return _binance_snapshot(client, symbol, int(order_id) if order_id else None, client_id)
    if exch == "bybit":
        return _bybit_snapshot(client, symbol, str(order_id) if order_id else None, client_id)
    if exch == "deribit":
        return _deribit_snapshot(client, symbol, str(order_id) if order_id else None, client_id)
    if exch == "kucoin":
        return _kucoin_snapshot(client, symbol, str(order_id) if order_id else None, client_id)
    if exch == "bitmart":
        return _bitmart_snapshot(client, symbol, str(order_id) if order_id else None, client_id)
    if exch == "okx":
        return _okx_snapshot(client, symbol, str(order_id) if order_id else None, client_id)
    raise SystemExit("Unsupported exchange for monitor")

# -------- CLI hook --------
def cli_monitor(args):
    if not args.exch:
        raise SystemExit("--exch is required for monitor command")
    client = make_client(args.exch, args.testnet)
    symbol = normalize_symbol_for_exchange(args.symbol, args.exch, "spot")
    snap = get_position_snapshot(args.exch, client, symbol, args.order_id, args.client_id)
    print(json.dumps(snap, indent=2))

def _debug_mark_price(exch: str, symbol: str, testnet: bool = True):
    """Debug function to test if mark prices are changing in real-time"""
    if not exch:
        raise SystemExit("--exch is required for debug-mark command")
    client = make_client(exch, testnet)
    symbol = normalize_symbol_for_exchange(symbol, exch, "spot")
    print(f"Testing live mark price for {exch} {symbol}...")
    
    for i in range(5):
        if exch == "binance":
            bt = client.book_ticker(symbol)
            bid = float(bt["bidPrice"])
            ask = float(bt["askPrice"])
            mid = (bid + ask) / 2.0
            print(f"  {i+1}: bid={bid:.2f}, ask={ask:.2f}, mid={mid:.2f}")
        elif exch == "bybit":
            tk = client.ticker(symbol)
            bid = float(tk.get("bid1Price") or tk.get("bidPrice") or 0)
            ask = float(tk.get("ask1Price") or tk.get("askPrice") or 0)
            mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("lastPrice") or 0)
            print(f"  {i+1}: bid={bid:.2f}, ask={ask:.2f}, mid={mid:.2f}")
        elif exch == "deribit":
            instr = DeribitClient.norm_instrument(symbol)
            tkr = client._get("/api/v2/public/ticker", {"instrument_name": instr})
            mark = float(tkr.get("mark_price") or tkr.get("last_price") or 0.0)
            print(f"  {i+1}: mark={mark:.2f}")
        elif exch == "kucoin":
            tk = client.ticker(symbol)
            bid = float(tk.get("bestBid", 0) or 0)
            ask = float(tk.get("bestAsk", 0) or 0)
            mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("price") or 0)
            print(f"  {i+1}: bid={bid:.2f}, ask={ask:.2f}, mid={mid:.2f}")
        elif exch == "bitmart":
            tk = client.ticker(symbol)
            bid = float(tk.get("best_bid", 0) or 0)
            ask = float(tk.get("best_ask", 0) or 0)
            mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("last_price") or 0)
            print(f"  {i+1}: bid={bid:.2f}, ask={ask:.2f}, mid={mid:.2f}")
        elif exch == "okx":
            tk = client.ticker(symbol)
            bid = float(tk.get("bidPx", 0) or 0)
            ask = float(tk.get("askPx", 0) or 0)
            mid = (bid + ask) / 2.0 if bid and ask else float(tk.get("last") or 0)
            print(f"  {i+1}: bid={bid:.2f}, ask={ask:.2f}, mid={mid:.2f}")
        
        if i < 4:  # don't sleep after last iteration
            time.sleep(1)
    
    print("Mark price test complete!")

def _test_symbol_mapping(raw_symbol: str, exchange: Optional[str] = None):
    """Test the symbol mapper with any symbol format"""
    print(f"Testing symbol mapping for: '{raw_symbol}'")
    print("=" * 50)
    
    try:
        info = symbol_mapper.parse(raw_symbol)
        print(f"Parsed Info:")
        print(f"  Raw: {info.raw}")
        print(f"  Base: {info.base}")
        print(f"  Quote: {info.quote}")
        print(f"  Canonical: {info.canonical}")
        print(f"  Is Perp: {info.is_perp}")
        print(f"  Multiplier: {info.multiplier}")
        print()
        print("Exchange-specific symbols:")
        for key, value in info.vendor.items():
            print(f"  {key}: {value}")
        print()
        
        # Test round-trip for each exchange
        exchanges = ["binance", "bybit", "deribit"]
        for exch in exchanges:
            product = "perp" if exch == "deribit" else "spot"
            mapped = normalize_symbol_for_exchange(raw_symbol, exch, product)
            print(f"  {exch} ({product}): '{raw_symbol}' -> '{mapped}'")
        
        # If specific exchange was provided, show detailed mapping
        if exchange:
            product = "perp" if exchange == "deribit" else "spot"
            mapped = normalize_symbol_for_exchange(raw_symbol, exchange, product)
            print(f"\nDetailed mapping for {exchange} ({product}):")
            print(f"  Input: '{raw_symbol}'")
            print(f"  Output: '{mapped}'")
            
    except Exception as e:
        print(f"Error parsing symbol: {e}")

def build_parser():
    p = argparse.ArgumentParser(description="Task 2: Trade Execution & Order Management (Binance + Bybit + Deribit + KuCoin + BitMart + OKX)")
    p.add_argument("--exch", choices=["binance", "bybit", "deribit", "kucoin", "bitmart", "okx"], help="Select exchange (not needed for symbol-test)")
    p.add_argument("--testnet", action="store_true", help="Use testnet (Note: KuCoin, BitMart, OKX require actual API keys)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("place", help="Place an order")
    sp.add_argument("symbol", help="Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)")
    sp.add_argument("--side", required=True, choices=["BUY", "SELL"])
    sp.add_argument("--type", required=True, choices=["LIMIT", "MARKET"])
    sp.add_argument("--qty", type=float, help="Base qty (or market by qty)")
    sp.add_argument("--quote", type=float, help="Market by quote (Binance quoteOrderQty; Bybit marketUnit=quoteCoin)")
    sp.add_argument("--price", type=float, help="Limit price")
    sp.add_argument("--tif", default="GTC", help="Time in force (LIMIT)")
    sp.add_argument("--client-id", dest="client_id", help="client id (Binance:newClientOrderId / Bybit:orderLinkId)")
    sp.add_argument("--test", action="store_true", help="Binance only: /order/test")
    sp.add_argument("--reduce-only", action="store_true", help="Deribit: place order as reduce_only")
    sp.set_defaults(func=lambda a: cli_place(a))

    sc = sub.add_parser("cancel", help="Cancel an open order")
    sc.add_argument("symbol", help="Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)")
    sc.add_argument("--order-id", help="orderId")
    sc.add_argument("--client-id", dest="client_id", help="client id / orderLinkId")
    sc.set_defaults(func=lambda a: cli_cancel(a))

    ss = sub.add_parser("status", help="Get order status")
    ss.add_argument("symbol", help="Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)")
    ss.add_argument("--order-id", help="orderId")
    ss.add_argument("--client-id", dest="client_id", help="client id / orderLinkId")
    ss.set_defaults(func=lambda a: cli_status(a))

    spf = sub.add_parser("perftest", help="Performance test (200 orders / 5 min default)")
    spf.add_argument("symbol", help="Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)")
    spf.add_argument("--count", type=int, default=200)
    spf.add_argument("--duration", type=int, default=300, help="seconds")
    spf.set_defaults(func=lambda a: cli_perftest(a))

    sm = sub.add_parser("monitor", help="Position & PnL snapshot from a FILLED order")
    sm.add_argument("symbol", help="Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)")
    sm.add_argument("--order-id")
    sm.add_argument("--client-id", dest="client_id")
    sm.set_defaults(func=cli_monitor)
    
    # Debug subcommand to test mark price changes
    sd = sub.add_parser("debug-mark", help="Debug: Test if mark prices are changing in real-time")
    sd.add_argument("symbol", help="Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)")
    sd.set_defaults(func=lambda a: _debug_mark_price(a.exch, a.symbol, a.testnet))
    
    # Symbol mapper test subcommand
    st = sub.add_parser("symbol-test", help="Test symbol mapping for any symbol format")
    st.add_argument("symbol", help="Any symbol format (BTCUSDT, BTC-USDT, BTC/USDT, etc.)")
    st.set_defaults(func=lambda a: _test_symbol_mapping(a.symbol, a.exch))
    
    return p

def main():
    load_dotenv()
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
