"""
Core funding functionality extracted from TASK1/1.3.py

Provides reusable functions for fetching funding rates from exchanges.
"""
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path to import original modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "TASK1"))

try:
    import importlib.util
    
    # Load the 1.3.py module
    spec = importlib.util.spec_from_file_location("funding_module", project_root / "TASK1" / "1.3.py")
    funding_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(funding_module)
    
    # Extract connector classes and utilities
    BinanceFunding = funding_module.BinanceFunding
    BybitFunding = funding_module.BybitFunding
    DeribitFunding = funding_module.DeribitFunding
    KucoinFuturesFunding = funding_module.KucoinFuturesFunding
    HyperliquidFunding = funding_module.HyperliquidFunding
    HOURS_PER_YEAR = funding_module.HOURS_PER_YEAR
    
except ImportError as e:
    print(f"Warning: Could not import funding modules: {e}")
    # Fallback classes for development
    class BinanceFunding: pass
    class BybitFunding: pass
    class DeribitFunding: pass
    class KucoinFuturesFunding: pass
    class HyperliquidFunding: pass
    HOURS_PER_YEAR = 24 * 365


EXCHANGE_CONNECTORS = {
    "binance": BinanceFunding,
    "bybit": BybitFunding,
    "deribit": DeribitFunding,
    "kucoin": KucoinFuturesFunding,
    "hyperliquid": HyperliquidFunding
}


def annualize(rate: float, period_hours: int) -> float:
    """
    Convert per-period funding rate to annualized APR.
    
    Args:
        rate: Funding rate per period (as decimal, e.g., 0.0001 = 0.01%)
        period_hours: Hours between funding payments
        
    Returns:
        Annualized APR as percentage
    """
    if period_hours <= 0:
        return 0.0
    
    periods_per_year = HOURS_PER_YEAR / period_hours
    return rate * periods_per_year * 100  # Convert to percentage


async def current_funding(exchange: str, symbol: str, period_hours: int = 8) -> Dict[str, Any]:
    """
    Get current funding rate for a symbol on an exchange.
    
    Args:
        exchange: Exchange name (binance, bybit, etc.)
        symbol: Trading pair symbol
        period_hours: Funding period in hours (default 8)
        
    Returns:
        Dict with current funding rate and derived APR
    """
    connector_class = EXCHANGE_CONNECTORS.get(exchange.lower())
    if not connector_class:
        raise ValueError(f"Unsupported exchange: {exchange}")
    
    # Create aiohttp session for the request
    import aiohttp
    async with aiohttp.ClientSession() as session:
        try:
            # Call the live method with appropriate parameters based on exchange
            if exchange.lower() == "bybit":
                result = await connector_class.live(session, symbol, category="linear")
            elif exchange.lower() == "hyperliquid":
                result = await connector_class.live(session, symbol)
            else:
                result = await connector_class.live(session, symbol)
            
            # Debug: print the raw result to see what fields are available
            print(f"[DEBUG] {exchange} raw result: {result}")
            
            # Extract funding rate from result - try different field names
            rate = 0.0
            if "current_rate" in result:
                rate = result["current_rate"]
            elif "fundingRate" in result:
                rate = result["fundingRate"]
            elif "funding_rate" in result:
                rate = result["funding_rate"]
            elif "rate" in result:
                rate = result["rate"]
            
            if rate is None:
                rate = 0.0
            if isinstance(rate, str):
                rate = float(rate)
            
            # Debug: print extracted rate
            print(f"[DEBUG] {exchange} extracted rate: {rate}")
            
            # Calculate APR
            apr = annualize(rate, period_hours)
            
            return {
                "exchange": exchange,
                "symbol": symbol,
                "funding_rate": rate,
                "funding_rate_pct": rate * 100,  # As percentage
                "apr": apr,
                "period_hours": period_hours,
                "next_funding_time": result.get("next_funding_time"),
                "countdown": result.get("countdown"),
                "timestamp": result.get("timestamp"),
                "raw_data": result
            }
            
        except Exception as e:
            print(f"Warning: Error fetching funding from {exchange}: {e}")
            return {
                "exchange": exchange,
                "symbol": symbol,
                "funding_rate": 0.0,
                "funding_rate_pct": 0.0,
                "period_hours": period_hours,
                "apr": 0.0,
                "error": str(e),
                "raw_data": {}
            }


async def funding_history(exchange: str, symbol: str, limit: int = 100, period_hours: int = 8) -> List[Dict[str, Any]]:
    """
    Get historical funding rates for a symbol on an exchange.
    
    Args:
        exchange: Exchange name
        symbol: Trading pair symbol  
        limit: Number of historical records to fetch
        period_hours: Funding period in hours
        
    Returns:
        List of historical funding rate records
    """
    connector_class = EXCHANGE_CONNECTORS.get(exchange.lower())
    if not connector_class:
        raise ValueError(f"Unsupported exchange: {exchange}")
    
    # Create aiohttp session for the request
    import aiohttp
    async with aiohttp.ClientSession() as session:
        try:
            # Call the history method with appropriate parameters based on exchange
            if exchange.lower() == "binance":
                results = await connector_class.history(session, symbol, limit=limit)
            elif exchange.lower() == "bybit":
                results = await connector_class.history(session, symbol, category="linear", limit=limit)
            elif exchange.lower() == "hyperliquid":
                results = await connector_class.history(session, symbol, limit=limit)
            else:
                results = await connector_class.history(session, symbol, limit=limit)
            
            history = []
            for result in results:
                # Extract funding rate from result - try different field names
                rate = 0.0
                if "fundingRate" in result:
                    rate = result["fundingRate"]
                elif "funding_rate" in result:
                    rate = result["funding_rate"]
                elif "current_rate" in result:
                    rate = result["current_rate"]
                elif "rate" in result:
                    rate = result["rate"]
                
                if rate is None:
                    rate = 0.0
                if isinstance(rate, str):
                    rate = float(rate)
                
                # Calculate APR for each record
                apr = annualize(rate, period_hours)
                
                history.append({
                    "exchange": exchange,
                    "symbol": symbol,
                    "funding_rate": rate,
                    "funding_rate_pct": rate * 100,
                    "apr": apr,
                    "timestamp": result.get("timestamp") or result.get("fundingTime"),
                    "funding_time": result.get("funding_time") or result.get("fundingTime")
                })
            
            return history
            
        except Exception as e:
            raise Exception(f"Error fetching funding history from {exchange}: {str(e)}")


async def get_multi_funding(exchanges: List[str], symbol: str, period_hours: int = 8) -> List[Dict[str, Any]]:
    """
    Fetch current funding rates from multiple exchanges concurrently.
    
    Args:
        exchanges: List of exchange names
        symbol: Trading pair symbol
        period_hours: Funding period in hours
        
    Returns:
        List of funding results, successful fetches only
    """
    tasks = []
    for exchange in exchanges:
        if exchange.lower() in EXCHANGE_CONNECTORS:
            tasks.append(current_funding(exchange, symbol, period_hours))
    
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


def get_funding_summary(funding_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate summary statistics for funding rates across exchanges.
    
    Args:
        funding_data: List of funding rate results
        
    Returns:
        Dict with summary statistics
    """
    if not funding_data:
        return {}
    
    rates = [d["funding_rate"] for d in funding_data]
    aprs = [d["apr"] for d in funding_data]
    
    return {
        "count": len(funding_data),
        "avg_rate": sum(rates) / len(rates),
        "avg_rate_pct": (sum(rates) / len(rates)) * 100,
        "avg_apr": sum(aprs) / len(aprs),
        "min_rate": min(rates),
        "max_rate": max(rates),
        "min_apr": min(aprs),
        "max_apr": max(aprs),
        "rate_spread": max(rates) - min(rates),
        "apr_spread": max(aprs) - min(aprs)
    }


def get_supported_exchanges() -> List[str]:
    """Get list of supported exchanges for funding data."""
    return list(EXCHANGE_CONNECTORS.keys())
