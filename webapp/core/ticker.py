"""
Core ticker functionality extracted from TASK1/1.1.py

Provides reusable functions for fetching best bid/ask data from exchanges.
"""
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path to import original modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "TASK1"))

try:
    # Import the original connectors from 1.1.py
    from binance_dual_source import binance_dual
    import importlib.util
    
    # Load the 1.1.py module
    spec = importlib.util.spec_from_file_location("ticker_module", project_root / "TASK1" / "1.1.py")
    ticker_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ticker_module)
    
    # Extract connector classes
    BitmartConnector = ticker_module.BitmartConnector
    BinanceConnector = ticker_module.BinanceConnector
    DeribitConnector = ticker_module.DeribitConnector
    KucoinConnector = ticker_module.KucoinConnector
    OkxConnector = ticker_module.OkxConnector
    HyperliquidConnector = ticker_module.HyperliquidConnector
    validate_token_format = ticker_module.validate_token_format
    
except ImportError as e:
    print(f"Warning: Could not import ticker modules: {e}")
    # Fallback classes for development
    class BitmartConnector: pass
    class BinanceConnector: pass
    class DeribitConnector: pass
    class KucoinConnector: pass
    class OkxConnector: pass
    class HyperliquidConnector: pass
    def validate_token_format(token): return True


EXCHANGE_CONNECTORS = {
    "bitmart": BitmartConnector,
    "binance": BinanceConnector, 
    "deribit": DeribitConnector,
    "kucoin": KucoinConnector,
    "okx": OkxConnector,
    "hyperliquid": HyperliquidConnector
}


async def get_best_bid_ask(exchange: str, symbol: str) -> Dict[str, Any]:
    """
    Get best bid/ask from a single exchange.
    
    Args:
        exchange: Exchange name (binance, bitmart, etc.)
        symbol: Trading pair symbol
        
    Returns:
        Dict with exchange, symbol, bid, ask, mid, ts_utc keys
    """
    if not validate_token_format(symbol):
        raise ValueError(f"Invalid token format: {symbol}")
    
    connector_class = EXCHANGE_CONNECTORS.get(exchange.lower())
    if not connector_class:
        raise ValueError(f"Unsupported exchange: {exchange}")
    
    connector = connector_class()
    try:
        result = await connector.get_best_bid_ask(symbol)
        
        # Standardize the response format
        bid = result["bid"]
        ask = result["ask"]
        mid = (bid + ask) / 2
        
        return {
            "exchange": exchange,
            "symbol": symbol,
            "raw_symbol": result.get("raw_symbol", symbol),
            "bid": bid,
            "ask": ask, 
            "mid": mid,
            "timestamp": result["timestamp"],
            "ts_utc": result.get("ts_utc"),
            "spread_bps": ((ask - bid) / mid) * 10000 if mid > 0 else 0
        }
    except Exception as e:
        raise Exception(f"Error fetching from {exchange}: {str(e)}")


async def get_multi_best_bid_ask(exchanges: List[str], symbol: str) -> List[Dict[str, Any]]:
    """
    Fetch best bid/ask from multiple exchanges concurrently.
    
    Args:
        exchanges: List of exchange names
        symbol: Trading pair symbol
        
    Returns:
        List of results, successful fetches only
    """
    if not validate_token_format(symbol):
        raise ValueError(f"Invalid token format: {symbol}")
    
    tasks = []
    for exchange in exchanges:
        if exchange.lower() in EXCHANGE_CONNECTORS:
            tasks.append(get_best_bid_ask(exchange, symbol))
    
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


def get_aggregated_best(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate results to find overall best bid/ask.
    
    Args:
        results: List of exchange results
        
    Returns:
        Dict with best_bid_exchange, best_ask_exchange, etc.
    """
    if not results:
        return {}
    
    # Separate spot and perpetual results
    spot_results = [r for r in results if r["exchange"] != "deribit"]
    perp_results = [r for r in results if r["exchange"] == "deribit"]
    
    aggregated = {"spot": {}, "perpetual": {}}
    
    if spot_results:
        best_bid = max(spot_results, key=lambda x: x["bid"])
        best_ask = min(spot_results, key=lambda x: x["ask"])
        mid = (best_bid["bid"] + best_ask["ask"]) / 2
        
        aggregated["spot"] = {
            "best_bid": best_bid["bid"],
            "best_bid_exchange": best_bid["exchange"],
            "best_ask": best_ask["ask"], 
            "best_ask_exchange": best_ask["exchange"],
            "mid": mid,
            "spread_bps": ((best_ask["ask"] - best_bid["bid"]) / mid) * 10000 if mid > 0 else 0
        }
    
    if perp_results:
        best_bid = max(perp_results, key=lambda x: x["bid"])
        best_ask = min(perp_results, key=lambda x: x["ask"])
        mid = (best_bid["bid"] + best_ask["ask"]) / 2
        
        aggregated["perpetual"] = {
            "best_bid": best_bid["bid"],
            "best_bid_exchange": best_bid["exchange"],
            "best_ask": best_ask["ask"],
            "best_ask_exchange": best_ask["exchange"], 
            "mid": mid,
            "spread_bps": ((best_ask["ask"] - best_bid["bid"]) / mid) * 10000 if mid > 0 else 0
        }
    
    return aggregated


def get_supported_exchanges() -> List[str]:
    """Get list of supported exchanges for ticker data."""
    return list(EXCHANGE_CONNECTORS.keys())
