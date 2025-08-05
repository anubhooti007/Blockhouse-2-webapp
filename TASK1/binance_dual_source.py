#!/usr/bin/env python3
"""
Binance Dual-Source Helper

Automatically selects between Binance.com and Binance.US based on:
1. Symbol availability 
2. Geo-blocking (HTTP 451)
3. Network errors

Provides transparent fallback without requiring CLI flags.
"""
import aiohttp
import asyncio
import logging
from typing import Dict, Set, Optional, Tuple

class BinanceDualSource:
    def __init__(self):
        self.global_base = "https://api.binance.com"
        self.global_fapi = "https://fapi.binance.com"
        self.us_base = "https://api.binance.us"
        
        # Symbol caches
        self.global_spot_symbols: Set[str] = set()
        self.global_futures_symbols: Set[str] = set()
        self.us_spot_symbols: Set[str] = set()
        
        # Cache initialization status
        self.cache_initialized = False
        
        # Logger
        self.logger = logging.getLogger("binance_dual_source")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('[%(levelname)s] %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    async def initialize_cache(self, session: aiohttp.ClientSession):
        """Fetch and cache symbol lists from both Binance endpoints"""
        if self.cache_initialized:
            return
            
        # Fetch Binance.com symbols
        try:
            # Spot symbols
            async with session.get(f"{self.global_base}/api/v3/exchangeInfo") as r:
                if r.status == 200:
                    data = await r.json()
                    for symbol_info in data.get("symbols", []):
                        if symbol_info.get("status") == "TRADING":
                            self.global_spot_symbols.add(symbol_info["symbol"])
                    self.logger.info(f"Cached {len(self.global_spot_symbols)} spot symbols from binance.com")
                else:
                    self.logger.warning(f"Failed to fetch binance.com spot symbols: HTTP {r.status}")
            
            # Futures symbols
            async with session.get(f"{self.global_fapi}/fapi/v1/exchangeInfo") as r:
                if r.status == 200:
                    data = await r.json()
                    for symbol_info in data.get("symbols", []):
                        if symbol_info.get("status") == "TRADING":
                            self.global_futures_symbols.add(symbol_info["symbol"])
                    self.logger.info(f"Cached {len(self.global_futures_symbols)} futures symbols from binance.com")
                else:
                    self.logger.warning(f"Failed to fetch binance.com futures symbols: HTTP {r.status}")
                    
        except Exception as e:
            self.logger.warning(f"Error fetching binance.com symbols: {e}")
        
        # Fetch Binance.US symbols
        try:
            async with session.get(f"{self.us_base}/api/v3/exchangeInfo") as r:
                if r.status == 200:
                    data = await r.json()
                    for symbol_info in data.get("symbols", []):
                        if symbol_info.get("status") == "TRADING":
                            self.us_spot_symbols.add(symbol_info["symbol"])
                    self.logger.info(f"Cached {len(self.us_spot_symbols)} spot symbols from binance.us")
                else:
                    self.logger.warning(f"Failed to fetch binance.us symbols: HTTP {r.status}")
        except Exception as e:
            self.logger.warning(f"Error fetching binance.us symbols: {e}")
        
        self.cache_initialized = True
    
    def _get_candidate_bases(self, symbol: str, is_futures: bool = False) -> list:
        """Get ordered list of candidate base URLs for a symbol"""
        candidates = []
        
        if is_futures:
            # Only Binance.com has futures
            if symbol in self.global_futures_symbols:
                candidates.append(self.global_fapi)
        else:
            # Try global first if symbol exists there
            if symbol in self.global_spot_symbols:
                candidates.append(self.global_base)
            
            # Add US if symbol exists there
            if symbol in self.us_spot_symbols:
                candidates.append(self.us_base)
            
            # If symbol not in either cache, try both anyway (cache might be stale)
            if not candidates:
                candidates = [self.global_base, self.us_base]
        
        return candidates
    
    async def fetch_json(self, session: aiohttp.ClientSession, symbol: str, path: str, 
                        params: Optional[Dict] = None, is_futures: bool = False) -> Dict:
        """
        Fetch JSON from Binance with automatic endpoint selection and fallback
        
        Args:
            session: aiohttp session
            symbol: Trading symbol (e.g., BTCUSDT)
            path: API path (e.g., /api/v3/ticker/bookTicker)
            params: Query parameters
            is_futures: Whether this is a futures API call
            
        Returns:
            JSON response data
            
        Raises:
            RuntimeError: If all endpoints fail
        """
        await self.initialize_cache(session)
        
        if params is None:
            params = {}
        
        candidates = self._get_candidate_bases(symbol, is_futures)
        last_error = None
        
        for base_url in candidates:
            try:
                url = f"{base_url}{path}"
                async with session.get(url, params=params) as r:
                    if r.status == 200:
                        data = await r.json()
                        source = "binance.com" if "binance.com" in base_url else "binance.us"
                        self.logger.info(f"{symbol}: fetched from {source}")
                        return data
                    elif r.status == 451:
                        source = "binance.com" if "binance.com" in base_url else "binance.us"
                        self.logger.warning(f"{symbol}: {source} returned 451 (geo-blocked), trying fallback")
                        last_error = f"HTTP 451 from {source}"
                        continue
                    else:
                        source = "binance.com" if "binance.com" in base_url else "binance.us"
                        error_text = await r.text()
                        last_error = f"HTTP {r.status} from {source}: {error_text[:100]}"
                        continue
                        
            except Exception as e:
                source = "binance.com" if "binance.com" in base_url else "binance.us"
                last_error = f"Network error from {source}: {e}"
                continue
        
        # All endpoints failed
        if not candidates:
            error_msg = f"{symbol}: not available on either Binance.com or Binance.US"
        else:
            sources_tried = [("binance.com" if "binance.com" in url else "binance.us") for url in candidates]
            error_msg = f"{symbol}: failed on all sources {sources_tried}. Last error: {last_error}"
        
        self.logger.error(error_msg)
        raise RuntimeError(error_msg)

# Global instance for all scripts to use
binance_dual = BinanceDualSource()