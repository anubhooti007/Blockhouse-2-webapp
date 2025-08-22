"""
Trading module for webapp - wraps TASK2.3.4/2.1.py functionality for testnet trading
"""
import os
import sys
import json
import time
import random
from pathlib import Path
from typing import Dict, Any, Optional, List

# Add TASK2.3.4 to path to import the trading client
task_path = Path(__file__).parent.parent.parent / "TASK2.3.4"
sys.path.insert(0, str(task_path))

try:
    from dotenv import load_dotenv
    load_dotenv()
    
    # Import the client classes and utilities from TASK2.3.4/2.1.py
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        # For type hints only
        from TASK2_3_4.py2_1 import BinanceClient, BybitClient, DeribitClient
    
    # Import necessary functions and classes
    import importlib.util
    spec = importlib.util.spec_from_file_location("trading_clients", task_path / "2.1.py")
    trading_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trading_module)
    
    # Extract what we need
    BinanceClient = trading_module.BinanceClient
    BybitClient = trading_module.BybitClient  
    DeribitClient = trading_module.DeribitClient
    normalize_symbol_for_exchange = trading_module.normalize_symbol_for_exchange
    
except Exception as e:
    print(f"Error importing trading module: {e}")
    # Fallback - create stub classes
    class BinanceClient:
        def __init__(self, *args, **kwargs): pass
        def place_order(self, *args, **kwargs): raise NotImplementedError("Trading module not available")
    
    class BybitClient:
        def __init__(self, *args, **kwargs): pass  
        def place_order(self, *args, **kwargs): raise NotImplementedError("Trading module not available")
    
    class DeribitClient:
        def __init__(self, *args, **kwargs): pass
        def place_order(self, *args, **kwargs): raise NotImplementedError("Trading module not available")
    
    def normalize_symbol_for_exchange(symbol, exchange, product="spot"):
        return symbol.upper()

def get_testnet_exchanges() -> List[str]:
    """Get list of supported testnet exchanges"""
    return ["binance", "bybit", "deribit"]

def make_client(exchange: str, testnet: bool = True):
    """Create trading client for specified exchange"""
    if not testnet:
        raise ValueError("Only testnet trading is supported in webapp")
    
    if exchange == "binance":
        key = os.getenv("BINANCE_API_KEY")
        secret = os.getenv("BINANCE_API_SECRET") 
        if not key or not secret:
            raise ValueError("Binance API credentials not found in environment")
        return BinanceClient(key, secret, testnet=True)
    
    elif exchange == "bybit":
        key = os.getenv("BYBIT_API_KEY")
        secret = os.getenv("BYBIT_API_SECRET")
        if not key or not secret:
            raise ValueError("Bybit API credentials not found in environment")
        return BybitClient(key, secret, testnet=True)
    
    elif exchange == "deribit":
        client_id = os.getenv("DERIBIT_CLIENT_ID")
        client_secret = os.getenv("DERIBIT_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ValueError("Deribit API credentials not found in environment")
        return DeribitClient(client_id, client_secret, testnet=True)
    
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")

def validate_order_params(side: str, order_type: str, qty: Optional[float], price: Optional[float], quote: Optional[float] = None, exchange: Optional[str] = None):
    """Validate order parameters"""
    if order_type == "MARKET":
        if not qty and not quote:
            raise ValueError("MARKET orders require either quantity or quote amount")
        if qty and qty <= 0:
            raise ValueError("Quantity must be greater than 0")
        if quote and quote <= 0:
            raise ValueError("Quote amount must be greater than 0")
        
        # Exchange-specific minimums
        if exchange and exchange.lower() == "bybit":
            if quote and quote < 50:
                raise ValueError("Bybit requires minimum quote amount of $50 USDT for market orders")
            if qty and qty < 0.000001:
                raise ValueError("Bybit requires minimum quantity of 0.000001 BTC")
    
    elif order_type == "LIMIT":
        if not qty or not price:
            raise ValueError("LIMIT orders require both quantity and price")
        if qty <= 0:
            raise ValueError("Quantity must be greater than 0")
        if price <= 0:
            raise ValueError("Price must be greater than 0")
            
        # Exchange-specific minimums for limit orders
        if exchange and exchange.lower() == "bybit":
            if qty < 0.000001:
                raise ValueError("Bybit requires minimum quantity of 0.000001 BTC")
    
    if side not in ["BUY", "SELL"]:
        raise ValueError("Side must be BUY or SELL")

def format_order_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """Format order response for display"""
    if not response:
        return {}
    
    # Extract order data from response
    order_data = response.get("order_response", {})
    latency = response.get("latency_ms", 0)
    
    # Standard fields to extract
    formatted = {
        "order_id": None,
        "client_order_id": None,
        "symbol": None,
        "side": None,
        "type": None,
        "quantity": None,
        "price": None,
        "status": None,
        "executed_qty": None,
        "executed_value": None,
        "avg_price": None,
        "latency_ms": latency
    }
    
    # Handle different exchange response formats
    if "orderId" in order_data:
        # Binance format
        formatted.update({
            "order_id": order_data.get("orderId"),
            "client_order_id": order_data.get("clientOrderId"),
            "symbol": order_data.get("symbol"),
            "side": order_data.get("side"),
            "type": order_data.get("type"),
            "quantity": order_data.get("origQty") or order_data.get("quantity"),
            "price": order_data.get("price"),
            "status": order_data.get("status"),
            "executed_qty": order_data.get("executedQty"),
            "executed_value": order_data.get("cummulativeQuoteQty"),
        })
        
        # Calculate average price if available
        exec_qty = float(order_data.get("executedQty", 0) or 0)
        exec_value = float(order_data.get("cummulativeQuoteQty", 0) or 0)
        if exec_qty > 0 and exec_value > 0:
            formatted["avg_price"] = exec_value / exec_qty
            # For filled market orders, use avg_price as the price
            if order_data.get("type") == "MARKET" and order_data.get("status") in ["FILLED", "PARTIALLY_FILLED"]:
                formatted["price"] = formatted["avg_price"]
    
    elif "orderLinkId" in order_data or "orderId" in str(order_data):
        # Bybit format
        formatted.update({
            "order_id": order_data.get("orderId"),
            "client_order_id": order_data.get("orderLinkId") or order_data.get("clientOrderId"),
            "symbol": order_data.get("symbol"),
            "side": order_data.get("side"),
            "type": order_data.get("orderType") or order_data.get("type"),
            "quantity": order_data.get("qty"),
            "price": order_data.get("price"),
            "status": order_data.get("orderStatus") or order_data.get("status"),
            "executed_qty": order_data.get("cumExecQty"),
            "executed_value": order_data.get("cumExecValue"),
        })
        
        # Calculate average price
        exec_qty = float(order_data.get("cumExecQty", 0) or 0)
        exec_value = float(order_data.get("cumExecValue", 0) or 0)
        if exec_qty > 0 and exec_value > 0:
            formatted["avg_price"] = exec_value / exec_qty
            # For filled market orders, use avg_price as the price
            if order_data.get("orderType") == "Market" and order_data.get("orderStatus") in ["Filled", "PartiallyFilled"]:
                formatted["price"] = formatted["avg_price"]
    
    elif "order_id" in order_data:
        # Deribit format
        formatted.update({
            "order_id": order_data.get("order_id"),
            "client_order_id": order_data.get("label"),
            "symbol": order_data.get("instrument_name"),
            "side": "BUY" if order_data.get("direction") == "buy" else "SELL",
            "type": order_data.get("order_type", "").upper(),
            "quantity": order_data.get("amount"),
            "price": order_data.get("price"),
            "status": order_data.get("order_state", "").upper(),
            "executed_qty": order_data.get("filled_amount"),
        })
    
    # Clean up None values and format numbers
    for key, value in formatted.items():
        if value is not None and key in ["quantity", "price", "executed_qty", "executed_value", "avg_price"]:
            try:
                formatted[key] = float(value)
            except (ValueError, TypeError):
                formatted[key] = value
    
    return formatted

def get_position_snapshot(exchange: str, symbol: str, order_id: Optional[str] = None, 
                         client_order_id: Optional[str] = None) -> Dict[str, Any]:
    """Get position snapshot with PnL calculation for a filled order"""
    try:
        client = make_client(exchange, testnet=True)
        norm_symbol = normalize_symbol_for_exchange(symbol, exchange)
        
        if not order_id and not client_order_id:
            return {"error": "Either order_id or client_order_id is required"}
        
        # Call the appropriate snapshot function based on exchange
        if exchange.lower() == "binance":
            return _binance_snapshot(client, norm_symbol, order_id, client_order_id)
        elif exchange.lower() == "bybit":
            return _bybit_snapshot(client, norm_symbol, order_id, client_order_id)
        elif exchange.lower() == "deribit":
            return _deribit_snapshot(client, norm_symbol, order_id, client_order_id)
        else:
            return {"error": f"Exchange {exchange} not supported for position monitoring"}
        
    except Exception as e:
        return {"error": str(e)}

def _iso(ms):
    """Convert timestamp to ISO format"""
    if ms is None:
        return None
    try:
        from datetime import datetime, timezone
        if isinstance(ms, str):
            ms = int(ms)
        if ms > 1e12:  # Microseconds
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        else:  # Seconds
            dt = datetime.fromtimestamp(ms, tz=timezone.utc)
        return dt.isoformat()
    except Exception:
        return str(ms)

def _binance_snapshot(client, symbol: str, order_id: str = None, client_id: str = None):
    """Binance position snapshot with correct PnL calculation"""
    try:
        # Convert order_id to int for Binance
        oid = int(order_id) if order_id else None
        
        # Get order details
        od = client.get_order(symbol, orderId=oid, origClientOrderId=client_id)
        if od.get("status") not in ("FILLED", "PARTIALLY_FILLED"):
            return {"error": f"Order not filled: {od.get('status')}"}
        
        side = od["side"].upper()
        exec_qty = float(od.get("executedQty", "0"))
        
        # Calculate average price from executed trades
        try:
            # Try to get actual trades for more accurate avg price
            tr = client._signed("GET", "/api/v3/myTrades", {"symbol": symbol, "orderId": od["orderId"]})
            if tr:
                notional = 0.0
                qty = 0.0
                et_ms = tr[0].get("time")
                for t in tr:
                    p = float(t["price"])
                    q = float(t["qty"])
                    notional += p * q
                    qty += q
                    if et_ms is None or int(t["time"]) < int(et_ms):
                        et_ms = t["time"]
                avg_px = notional / qty if qty else float("nan")
                exec_qty = qty
            else:
                # Fallback to cumulative quote / executed qty
                if exec_qty > 0:
                    avg_px = float(od.get("cummulativeQuoteQty", "0")) / exec_qty
                    et_ms = od.get("transactTime") or od.get("time")
                else:
                    return {"error": "No trades found for filled order"}
        except Exception:
            # Final fallback to order price
            avg_px = float(od.get("price", "0"))
            et_ms = od.get("transactTime") or od.get("time")
        
        # Get current market price
        bt = client.book_ticker(symbol)
        bid = float(bt["bidPrice"])
        ask = float(bt["askPrice"])
        mid = (bid + ask) / 2.0
        
        # Calculate PnL
        if side == "BUY":
            pnl = (mid - avg_px) * exec_qty
        else:
            pnl = (avg_px - mid) * exec_qty
        
        denom = (avg_px * exec_qty) if (avg_px and exec_qty) else 1.0
        pnl_pct = (pnl / denom * 100) if denom and denom != 0 else 0.0
        
        return {
            "connector_name": "BINANCE",
            "pair_name": symbol,
            "entry_timestamp": _iso(et_ms),
            "entry_price": avg_px,
            "quantity": exec_qty,
            "position_side": "long" if side == "BUY" else "short",
            "current_price": mid,
            "NetPnL": pnl,
            "unrealized_pnl": pnl,
            "NetPnL_pct": pnl_pct
        }
        
    except Exception as e:
        return {"error": f"Binance snapshot failed: {str(e)}"}

def _bybit_snapshot(client, symbol: str, order_id: str = None, client_id: str = None):
    """Bybit position snapshot with correct PnL calculation"""
    try:
        # Get order details
        od = client.get_order(symbol, orderId=order_id, origClientOrderId=client_id)
        if not od:
            return {"error": "Order not found"}
        
        status = od.get("orderStatus", "")
        if status.upper() not in ("FILLED", "PARTIALLY_FILLED"):
            return {"error": f"Order not filled: {status}"}
        
        side = "BUY" if (od.get("side", "").lower() == "buy") else "SELL"
        avg_px = float(od.get("avgPrice") or 0.0)
        exec_qty = float(od.get("cumExecQty") or 0.0)
        et_ms = int(od.get("createdTime") or od.get("createTime") or od.get("updatedTime") or 0)
        
        if avg_px == 0 or exec_qty == 0:
            return {"error": "No execution data found for order"}
        
        # Get current market price
        tk = client.ticker(symbol)
        if tk:
            bid = float(tk.get("bid1Price") or 0)
            ask = float(tk.get("ask1Price") or 0) 
            last = float(tk.get("lastPrice") or 0)
            mid = (bid + ask) / 2.0 if bid and ask else last
        else:
            mid = avg_px  # Fallback to entry price
        
        # Calculate PnL
        if side == "BUY":
            pnl = (mid - avg_px) * exec_qty
        else:
            pnl = (avg_px - mid) * exec_qty
        
        denom = (avg_px * exec_qty) if (avg_px and exec_qty) else 1.0
        pnl_pct = (pnl / denom * 100) if denom and denom != 0 else 0.0
        
        return {
            "connector_name": "BYBIT",
            "pair_name": symbol,
            "entry_timestamp": _iso(et_ms),
            "entry_price": avg_px,
            "quantity": exec_qty,
            "position_side": "long" if side == "BUY" else "short",
            "current_price": mid,
            "NetPnL": pnl,
            "unrealized_pnl": pnl,
            "NetPnL_pct": pnl_pct
        }
        
    except Exception as e:
        return {"error": f"Bybit snapshot failed: {str(e)}"}

def _deribit_snapshot(client, symbol: str, order_id: str = None, client_id: str = None):
    """Deribit position snapshot with correct PnL calculation"""
    try:
        # Get order details
        od = client.get_order(symbol, orderId=order_id, origClientOrderId=client_id)
        if not od:
            return {"error": "Order not found"}
        
        status = od.get("order_state", "")
        if status.lower() not in ("filled", "partially_filled"):
            return {"error": f"Order not filled: {status}"}
        
        side = "BUY" if (od.get("direction", "").lower() == "buy") else "SELL"
        avg_px = float(od.get("average_price") or 0.0)
        exec_qty = float(od.get("filled_amount") or 0.0)
        et_ms = int(od.get("creation_timestamp") or 0)
        
        if avg_px == 0 or exec_qty == 0:
            return {"error": "No execution data found for order"}
        
        # Get current mark price from Deribit
        instrument = od.get("instrument_name", symbol)
        try:
            ticker = client.ticker(instrument)
            mid = float(ticker.get("mark_price", 0)) or float(ticker.get("last_price", 0))
        except Exception:
            mid = avg_px  # Fallback to entry price
        
        # Calculate PnL
        if side == "BUY":
            pnl = (mid - avg_px) * exec_qty
        else:
            pnl = (avg_px - mid) * exec_qty
        
        denom = (avg_px * exec_qty) if (avg_px and exec_qty) else 1.0
        pnl_pct = (pnl / denom * 100) if denom and denom != 0 else 0.0
        
        return {
            "connector_name": "DERIBIT",
            "pair_name": instrument,
            "entry_timestamp": _iso(et_ms),
            "entry_price": avg_px,
            "quantity": exec_qty,
            "position_side": "long" if side == "BUY" else "short",
            "current_price": mid,
            "NetPnL": pnl,
            "unrealized_pnl": pnl,
            "NetPnL_pct": pnl_pct
        }
        
    except Exception as e:
        return {"error": f"Deribit snapshot failed: {str(e)}"}

def performance_test_testnet(exchange: str, symbol: str, count: int = 10, duration: int = 60) -> Dict[str, Any]:
    """Run performance test placing and cancelling orders"""
    try:
        client = make_client(exchange, testnet=True)
        norm_symbol = normalize_symbol_for_exchange(symbol, exchange)
        
        results = {
            "total_orders": 0,
            "successful_orders": 0,
            "failed_orders": 0,
            "successful_cancels": 0,
            "failed_cancels": 0,
            "avg_place_latency": 0,
            "avg_cancel_latency": 0,
            "orders": []
        }
        
        place_latencies = []
        cancel_latencies = []
        
        import time
        start_time = time.time()
        
        for i in range(count):
            # Check if we've exceeded duration
            if time.time() - start_time > duration:
                break
            
            try:
                # Place a small limit order away from market
                order_start = time.time()
                
                # Get current price to set limit order away from market
                if exchange == "binance":
                    ticker = client.book_ticker(norm_symbol)
                    market_price = float(ticker.get("bidPrice", 50000))
                elif exchange == "bybit":
                    ticker = client.ticker(norm_symbol)
                    ticker_data = ticker.get("result", {}).get("list", [{}])[0] if ticker.get("result") else {}
                    market_price = float(ticker_data.get("bid1Price", 50000))
                else:
                    market_price = 50000  # Fallback
                
                # Set limit price 15% away from market
                limit_price = market_price * 0.85 if i % 2 == 0 else market_price * 1.15
                side = "BUY" if i % 2 == 0 else "SELL"
                
                order_response = client.place_order(
                    symbol=norm_symbol,
                    side=side,
                    type_="LIMIT",
                    quantity=0.001,
                    price=limit_price
                )
                
                order_end = time.time()
                place_latency = (order_end - order_start) * 1000
                place_latencies.append(place_latency)
                
                results["total_orders"] += 1
                results["successful_orders"] += 1
                
                # Extract order ID for cancellation
                order_id = None
                if "orderId" in order_response:
                    order_id = order_response["orderId"]
                elif "orderLinkId" in order_response:
                    order_id = order_response["orderLinkId"]
                elif "order_id" in order_response:
                    order_id = order_response["order_id"]
                
                # Try to cancel the order
                if order_id:
                    try:
                        cancel_start = time.time()
                        cancel_response = client.cancel_order(
                            symbol=norm_symbol,
                            orderId=order_id
                        )
                        cancel_end = time.time()
                        cancel_latency = (cancel_end - cancel_start) * 1000
                        cancel_latencies.append(cancel_latency)
                        results["successful_cancels"] += 1
                        
                        results["orders"].append({
                            "order_id": order_id,
                            "side": side,
                            "price": limit_price,
                            "place_latency": place_latency,
                            "cancel_latency": cancel_latency,
                            "status": "cancelled"
                        })
                        
                    except Exception as cancel_error:
                        results["failed_cancels"] += 1
                        results["orders"].append({
                            "order_id": order_id,
                            "side": side,
                            "price": limit_price,
                            "place_latency": place_latency,
                            "cancel_error": str(cancel_error),
                            "status": "cancel_failed"
                        })
                
            except Exception as order_error:
                results["failed_orders"] += 1
                results["total_orders"] += 1
                results["orders"].append({
                    "error": str(order_error),
                    "status": "place_failed"
                })
            
            # Small delay between orders
            time.sleep(0.1)
        
        # Calculate averages
        if place_latencies:
            results["avg_place_latency"] = sum(place_latencies) / len(place_latencies)
        if cancel_latencies:
            results["avg_cancel_latency"] = sum(cancel_latencies) / len(cancel_latencies)
        
        results["duration"] = time.time() - start_time
        results["success_rate"] = (results["successful_orders"] / results["total_orders"]) * 100 if results["total_orders"] > 0 else 0
        results["cancel_rate"] = (results["successful_cancels"] / results["successful_orders"]) * 100 if results["successful_orders"] > 0 else 0
        
        return results
        
    except Exception as e:
        return {"error": str(e)}

def place_order_testnet(exchange: str, symbol: str, side: str, order_type: str, 
                       qty: Optional[float] = None, price: Optional[float] = None,
                       quote: Optional[float] = None) -> Dict[str, Any]:
    """Place order on testnet"""
    try:
        # Create client
        client = make_client(exchange, testnet=True)
        
        # Normalize symbol
        normalized_symbol = normalize_symbol_for_exchange(symbol, exchange, "spot")
        
        # Generate client order ID
        client_order_id = f"webapp_{random.randbytes(6).hex()}"
        
        # Build order parameters
        order_params = {
            "symbol": normalized_symbol,
            "side": side.upper(),
            "type_": order_type.upper(),
            "newClientOrderId": client_order_id,
            "test": False  # Real testnet order, not test endpoint
        }
        
        # Add quantity/price based on order type
        if order_type.upper() == "MARKET":
            if quote:
                order_params["quoteOrderQty"] = quote
            elif qty:
                order_params["quantity"] = qty
            else:
                raise ValueError("MARKET orders require either quantity or quote amount")
        
        elif order_type.upper() == "LIMIT":
            if not qty or not price:
                raise ValueError("LIMIT orders require both quantity and price") 
            order_params["quantity"] = qty
            order_params["price"] = price
            order_params["timeInForce"] = "GTC"  # Good Till Cancelled
        
        # Place the order
        response = client.place_order(**order_params)
        
        return {
            "success": True,
            "exchange": exchange,
            "symbol": symbol,
            "response": response
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "exchange": exchange,
            "symbol": symbol
        }

def cancel_order_testnet(exchange: str, symbol: str, order_id: str) -> Dict[str, Any]:
    """Cancel order on testnet"""
    try:
        client = make_client(exchange, testnet=True)
        normalized_symbol = normalize_symbol_for_exchange(symbol, exchange, "spot")
        
        # Try to parse as integer for Binance
        try:
            order_id_int = int(order_id)
            response = client.cancel_order(normalized_symbol, orderId=order_id_int)
        except ValueError:
            # Use as string for other exchanges
            response = client.cancel_order(normalized_symbol, orderId=order_id)
        
        return {
            "success": True,
            "exchange": exchange,
            "cancel_response": response
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "exchange": exchange
        }

def order_status_testnet(exchange: str, symbol: str, order_id: str) -> Dict[str, Any]:
    """Get order status on testnet"""
    try:
        client = make_client(exchange, testnet=True)
        normalized_symbol = normalize_symbol_for_exchange(symbol, exchange, "spot")
        
        # Try to parse as integer for Binance
        try:
            order_id_int = int(order_id)
            response = client.get_order(normalized_symbol, orderId=order_id_int)
        except ValueError:
            # Use as string for other exchanges
            response = client.get_order(normalized_symbol, orderId=order_id)
        
        return {
            "success": True,
            "exchange": exchange,
            "order_status": response
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "exchange": exchange
        }
