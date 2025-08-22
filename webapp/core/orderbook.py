"""
Core orderbook functionality extracted from TASK1/1.2.py

Provides reusable functions for fetching L2 order book data from exchanges.
"""
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Add project root to path to import original modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "TASK1"))

try:
    import importlib.util
    
    # Load the 1.2.py module
    spec = importlib.util.spec_from_file_location("orderbook_module", project_root / "TASK1" / "1.2.py")
    orderbook_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orderbook_module)
    
    # Extract connector classes and utilities
    BinanceL2 = orderbook_module.BinanceL2
    KucoinL2 = orderbook_module.KucoinL2
    BybitL2 = orderbook_module.BybitL2
    DeribitL2 = orderbook_module.DeribitL2
    BitmartL2 = orderbook_module.BitmartL2
    OkxL2 = orderbook_module.OkxL2
    HyperliquidL2 = orderbook_module.HyperliquidL2
    mid_spread = orderbook_module.mid_spread
    
except ImportError as e:
    print(f"Warning: Could not import orderbook modules: {e}")
    # Fallback classes for development
    class BinanceL2: pass
    class KucoinL2: pass
    class BybitL2: pass
    class DeribitL2: pass
    class BitmartL2: pass
    class OkxL2: pass
    class HyperliquidL2: pass
    def mid_spread(bids, asks): return None, None, None


EXCHANGE_CONNECTORS = {
    "binance": BinanceL2,
    "kucoin": KucoinL2,
    "bybit": BybitL2,
    "deribit": DeribitL2,
    "bitmart": BitmartL2,
    "okx": OkxL2,
    "hyperliquid": HyperliquidL2
}


async def get_l2_orderbook(exchange: str, symbol: str, limit: int = 200) -> Dict[str, Any]:
    """
    Get L2 order book from a single exchange.
    
    Args:
        exchange: Exchange name (binance, kucoin, etc.)
        symbol: Trading pair symbol
        limit: Maximum depth to fetch
        
    Returns:
        Dict with bids, asks, best_bid, best_ask, mid, spread_bps
    """
    connector_class = EXCHANGE_CONNECTORS.get(exchange.lower())
    if not connector_class:
        raise ValueError(f"Unsupported exchange: {exchange}")
    
    connector = connector_class()
    
    # Create aiohttp session for the request
    import aiohttp
    async with aiohttp.ClientSession() as session:
        try:
            # Fetch order book data
            result = await connector.fetch_l2(session, symbol, limit=limit)
            
            # Extract bids and asks
            bids = result.get("bids", [])
            asks = result.get("asks", [])
            
            # Convert to list of tuples if needed
            if bids and isinstance(bids[0], list):
                bids = [(float(p), float(q)) for p, q in bids]
            if asks and isinstance(asks[0], list):
                asks = [(float(p), float(q)) for p, q in asks]
            
            # Calculate mid price and spread
            mid, spread, spread_bps = mid_spread(bids, asks)
            
            best_bid = bids[0][0] if bids else None
            best_ask = asks[0][0] if asks else None
            
            return {
                "exchange": exchange,
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "spread": spread,
                "spread_bps": spread_bps,
                "timestamp": result.get("timestamp"),
                "bid_count": len(bids),
                "ask_count": len(asks)
            }
            
        except Exception as e:
            raise Exception(f"Error fetching orderbook from {exchange}: {str(e)}")


async def get_multi_orderbooks(exchanges: List[str], symbol: str, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Fetch order books from multiple exchanges concurrently.
    
    Args:
        exchanges: List of exchange names
        symbol: Trading pair symbol
        limit: Maximum depth to fetch
        
    Returns:
        List of orderbook results, successful fetches only
    """
    tasks = []
    for exchange in exchanges:
        if exchange.lower() in EXCHANGE_CONNECTORS:
            tasks.append(get_l2_orderbook(exchange, symbol, limit))
    
    if not tasks:
        return []
    
    results = []
    try:
        # Run all tasks concurrently, but handle failures gracefully
        for task in asyncio.as_completed(tasks):
            try:
                result = await task
                results.append(result)
            except Exception as e:
                # Log error but continue with other exchanges
                print(f"Warning: {str(e)}")
                continue
    except Exception:
        pass
    
    return results


def get_book_summary(orderbook: Dict[str, Any], top_n: int = 10) -> Dict[str, Any]:
    """
    Get summary statistics for an order book.
    
    Args:
        orderbook: Order book data
        top_n: Number of top levels to include
        
    Returns:
        Dict with summary statistics
    """
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])
    
    # Top N levels
    top_bids = bids[:top_n]
    top_asks = asks[:top_n]
    
    # Calculate total volumes at different depths
    bid_volumes = {}
    ask_volumes = {}
    
    cumulative_bid_vol = 0
    cumulative_ask_vol = 0
    
    for i, (price, qty) in enumerate(bids):
        cumulative_bid_vol += qty
        if i + 1 in [1, 5, 10, 25, 50, 100]:
            bid_volumes[f"top_{i+1}"] = cumulative_bid_vol
    
    for i, (price, qty) in enumerate(asks):
        cumulative_ask_vol += qty
        if i + 1 in [1, 5, 10, 25, 50, 100]:
            ask_volumes[f"top_{i+1}"] = cumulative_ask_vol
    
    return {
        "exchange": orderbook.get("exchange"),
        "symbol": orderbook.get("symbol"),
        "top_bids": top_bids,
        "top_asks": top_asks,
        "bid_volumes": bid_volumes,
        "ask_volumes": ask_volumes,
        "total_bid_levels": len(bids),
        "total_ask_levels": len(asks),
        "best_bid": orderbook.get("best_bid"),
        "best_ask": orderbook.get("best_ask"),
        "mid": orderbook.get("mid"),
        "spread_bps": orderbook.get("spread_bps")
    }


def get_supported_exchanges() -> List[str]:
    """Get list of supported exchanges for orderbook data."""
    return list(EXCHANGE_CONNECTORS.keys())
