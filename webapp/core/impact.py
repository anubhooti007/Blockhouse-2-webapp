"""
Core price impact functionality extracted from TASK1/1.4.py

Provides reusable functions for calculating price impact by walking order books.
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
    
    # Load the 1.4.py module
    spec = importlib.util.spec_from_file_location("impact_module", project_root / "TASK1" / "1.4.py")
    impact_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(impact_module)
    
    # Extract functions and classes we need
    fetch_one = impact_module.fetch_one
    compute_impact = impact_module.compute_impact
    walk_book_buy = impact_module.walk_book_buy
    walk_book_sell = impact_module.walk_book_sell
    compute_mid = impact_module.compute_mid
    impact_metrics = impact_module.impact_metrics
    
except ImportError as e:
    print(f"Warning: Could not import impact modules: {e}")
    # Fallback functions for development
    def fetch_one(exchange, symbol, session): return {}
    def compute_impact(book, side, notional): return {}
    def walk_book_buy(asks, notional): return 0, [], 0, 0, False
    def walk_book_sell(bids, notional): return 0, [], 0, 0, False
    def compute_mid(bids, asks): return 0
    def impact_metrics(avg, mid, side): return {}


async def estimate_price_impact(exchange: str, symbol: str, side: str, notional: float, limit: int = 200) -> Dict[str, Any]:
    """
    Estimate price impact by walking the order book.
    
    Args:
        exchange: Exchange name (binance, bybit, etc.)
        symbol: Trading pair symbol
        side: 'buy' or 'sell'
        notional: Notional amount in USDT to trade
        limit: Order book depth to fetch
        
    Returns:
        Dict with avg_exec, mid, impact_bps, levels_touched, filled_qty, filled
    """
    # Create aiohttp session for the request
    import aiohttp
    async with aiohttp.ClientSession() as session:
        try:
            # Use the fetch_one function from TASK1/1.4.py to get order book
            book_data = await fetch_one(exchange.lower(), symbol, session)
            
            # Calculate price impact using compute_impact function
            impact_result = compute_impact(book_data, side, notional)
            
            return {
                "exchange": exchange,
                "symbol": symbol,
                "side": side,
                "notional": notional,
                "mid": impact_result.get("market_mid_price"),
                "best_bid": impact_result.get("best_bid"),
                "best_ask": impact_result.get("best_ask"),
                "avg_exec": impact_result.get("avg_execution_price"),
                "impact_bps": impact_result.get("impact_bps"),
                "levels_touched": impact_result.get("levels_touched"),
                "filled_qty": impact_result.get("base_filled"),
                "filled": impact_result.get("fully_filled", False),
                "total_levels": len(book_data.get("bids", [])) if side == "sell" else len(book_data.get("asks", [])),
                "timestamp": impact_result.get("timestamp"),
                "spread_bps": impact_result.get("spread_bps")
            }
            
        except Exception as e:
            raise Exception(f"Error calculating impact for {exchange}: {str(e)}")


async def get_multi_impact(exchanges: List[str], symbol: str, side: str, notional: float, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Calculate price impact across multiple exchanges concurrently.
    
    Args:
        exchanges: List of exchange names
        symbol: Trading pair symbol
        side: 'buy' or 'sell'
        notional: Notional amount in USDT
        limit: Order book depth to fetch
        
    Returns:
        List of impact results, successful calculations only
    """
    tasks = []
    # Supported exchanges from TASK1/1.4.py
    supported_exchanges = ["binance", "bybit", "kucoin", "deribit", "hyperliquid"]
    
    for exchange in exchanges:
        if exchange.lower() in supported_exchanges:
            tasks.append(estimate_price_impact(exchange, symbol, side, notional, limit))
    
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


def compare_impacts(impact_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compare price impact results across exchanges.
    
    Args:
        impact_results: List of impact calculation results
        
    Returns:
        Dict with comparison statistics
    """
    if not impact_results:
        return {}
    
    # Filter only successfully filled orders
    filled_results = [r for r in impact_results if r.get("filled", False)]
    
    if not filled_results:
        return {"error": "No exchanges could fill the order"}
    
    # Find best execution
    best_execution = None
    if filled_results[0]["side"].lower() == "buy":
        # For buys, lower average execution price is better
        best_execution = min(filled_results, key=lambda x: x.get("avg_exec", float("inf")))
    else:
        # For sells, higher average execution price is better
        best_execution = max(filled_results, key=lambda x: x.get("avg_exec", 0))
    
    # Calculate statistics
    impacts = [r.get("impact_bps", 0) for r in filled_results]
    avg_execs = [r.get("avg_exec", 0) for r in filled_results]
    
    return {
        "total_exchanges": len(impact_results),
        "fillable_exchanges": len(filled_results),
        "best_exchange": best_execution.get("exchange"),
        "best_avg_exec": best_execution.get("avg_exec"),
        "best_impact_bps": best_execution.get("impact_bps"),
        "avg_impact_bps": sum(impacts) / len(impacts) if impacts else 0,
        "min_impact_bps": min(impacts) if impacts else 0,
        "max_impact_bps": max(impacts) if impacts else 0,
        "impact_spread_bps": (max(impacts) - min(impacts)) if impacts else 0,
        "avg_exec_spread": (max(avg_execs) - min(avg_execs)) if avg_execs else 0,
        "results": filled_results
    }


def get_depth_summary(impact_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get summary of order book depth utilization.
    
    Args:
        impact_result: Result from estimate_price_impact
        
    Returns:
        Dict with depth utilization statistics
    """
    levels_touched = impact_result.get("levels_touched", 0)
    total_levels = impact_result.get("total_levels", 0)
    
    # Handle None values
    if levels_touched is None:
        levels_touched = 0
    if total_levels is None:
        total_levels = 0
    
    # Ensure they are integers
    levels_touched = int(levels_touched) if levels_touched is not None else 0
    total_levels = int(total_levels) if total_levels is not None else 0
    
    utilization_pct = (levels_touched / total_levels * 100) if total_levels > 0 else 0
    
    return {
        "levels_touched": levels_touched,
        "total_levels": total_levels,
        "utilization_pct": utilization_pct,
        "filled": impact_result.get("filled", False),
        "remaining_levels": max(0, total_levels - levels_touched)
    }


def get_supported_exchanges() -> List[str]:
    """Get list of supported exchanges for price impact analysis."""
    return ["binance", "bybit", "kucoin", "deribit", "hyperliquid"]
