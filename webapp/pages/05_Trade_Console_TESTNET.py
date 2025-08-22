"""
Trading Console Page - TESTNET-only order management and trading

Powered by TASK2.3.4/2.1.py (TESTNET ONLY)
"""
import streamlit as st
import json
from datetime import datetime
import sys
from pathlib import Path

# Add webapp to path
webapp_root = Path(__file__).parent.parent
sys.path.insert(0, str(webapp_root))

try:
    from core.trade import (
        place_order_testnet, cancel_order_testnet, order_status_testnet,
        get_testnet_exchanges, validate_order_params, format_order_response,
        get_position_snapshot, performance_test_testnet
    )
    from utils.env import get_secret, is_testnet
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.stop()

# Page configuration
st.set_page_config(
    page_title="Trading Console - Crypto Tools",
    page_icon="🔶",
    layout="wide"
)

# Custom CSS for trading interface
st.markdown("""
<style>
    .trade-container {
        padding: 1.5rem;
        border-radius: 0.5rem;
        border: 2px solid #333;
        margin: 1rem 0;
    }
    .buy-container {
        border-left: 4px solid #00ff88;
        background-color: rgba(0, 255, 136, 0.1);
    }
    .sell-container {
        border-left: 4px solid #ff6b6b;
        background-color: rgba(255, 107, 107, 0.1);
    }
    .warning-banner {
        padding: 0.3rem 0.5rem;
        border-left: 4px solid #ff6b6b;
        background-color: rgba(255, 107, 107, 0.1);
        margin: 0.5rem 0;
        font-size: 0.9rem;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #00ff88;
        background-color: rgba(0, 255, 136, 0.1);
        margin: 1rem 0;
    }
    .error-box {
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #ff6b6b;
        background-color: rgba(255, 107, 107, 0.1);
        margin: 1rem 0;
    }
    /* Reduce size of success/error bars */
    .stAlert {
        padding: 0.3rem 0.5rem !important;
        margin: 0.2rem 0 !important;
        font-size: 0.85rem !important;
    }
    .stAlert > div {
        padding: 0.2rem !important;
    }
    /* Reduce height of any large colored bars */
    div[data-testid="stNotification"] {
        height: auto !important;
        min-height: 2rem !important;
        padding: 0.3rem !important;
    }
</style>
""", unsafe_allow_html=True)

# Header with warning
st.title("Trading Console")
st.markdown("*TESTNET-only order management and trading interface*")
st.caption("Powered by TASK2.3.4/2.1.py")

# Minimal testnet warning
st.markdown("""
<div class="warning-banner">
    <strong>TESTNET ONLY</strong> - Uses fake money on test environments
</div>
""", unsafe_allow_html=True)

# Sidebar controls
st.sidebar.header("Trade Parameters")

# Exchange selection
exchange = st.sidebar.selectbox(
    "Exchange",
    options=get_testnet_exchanges(),
    help="Select testnet exchange"
)

# Symbol input
symbol = st.sidebar.text_input(
    "Trading Pair",
    value="BTCUSDT",
    help="Enter symbol (format auto-detected)"
).strip().upper()

# Trade operation tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Place Order", "Cancel Order", "Order Status", "Position Monitor", "Performance Test"])

# Session state for storing orders
if "placed_orders" not in st.session_state:
    st.session_state.placed_orders = []

with tab1:
    st.subheader("Place New Order")
    
    # Helpful testnet guidance
    st.info("""
    💡 **Testnet Tips**: Start with moderate test orders (0.01 BTC ≈ $1,000) to properly test the interface. 
    Get free testnet funds from your exchange's faucet if orders fail due to insufficient balance.
    """)
    
    if not symbol:
        st.warning("Please enter a trading pair symbol")
    else:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="trade-container buy-container">', unsafe_allow_html=True)
            st.markdown("** BUY ORDER**")
            
            # Order type selection outside form for reactivity
            buy_type = st.selectbox("Order Type", ["MARKET", "LIMIT"], key="buy_type")
            
            # Amount type selection outside form for MARKET orders
            if buy_type == "MARKET":
                buy_amount_type = st.radio("Amount Type", ["Quantity", "Quote (USDT)"], key="buy_amount")
            
            # Buy order form
            with st.form("buy_order_form"):
                if buy_type == "MARKET":
                    if buy_amount_type == "Quantity":
                        buy_qty = st.number_input("Quantity", min_value=0.000001, value=0.01, step=0.001, format="%.6f", key="buy_qty", help="Enter quantity > 0 (Try 0.01 for testing)")
                        buy_quote = None
                    else:
                        buy_quote = st.number_input("Quote Amount (USDT)", min_value=50.0, value=500.0, step=10.0, key="buy_quote", help="Enter USDT amount > 0 (Bybit min: $50, Try $500 for testing)")
                        buy_qty = None
                    
                    buy_price = None
                else:  # LIMIT
                    buy_qty = st.number_input("Quantity", min_value=0.000001, value=0.01, step=0.001, format="%.6f", key="buy_qty_limit", help="Enter quantity > 0 (Try 0.01 for testing)")
                    buy_price = st.number_input("Price", min_value=0.01, value=95000.0, step=100.0, format="%.2f", key="buy_price", help="Enter price > 0 (Try current market price)")
                    buy_quote = None
                
                buy_submit = st.form_submit_button("Place BUY Order", type="primary")
                
                if buy_submit:
                    try:
                        # Additional validation for zero values
                        if buy_type == "MARKET":
                            if buy_amount_type == "Quantity" and (buy_qty is None or buy_qty <= 0):
                                st.error("Please enter a valid quantity greater than 0")
                                st.stop()
                            elif buy_amount_type == "Quote (USDT)" and (buy_quote is None or buy_quote <= 0):
                                st.error("Please enter a valid quote amount greater than 0")
                                st.stop()
                        else:  # LIMIT
                            if buy_qty is None or buy_qty <= 0:
                                st.error("Please enter a valid quantity greater than 0")
                                st.stop()
                            if buy_price is None or buy_price <= 0:
                                st.error("Please enter a valid price greater than 0")
                                st.stop()
                        
                        # Validate parameters
                        validate_order_params("BUY", buy_type, buy_qty, buy_price, quote=buy_quote, exchange=exchange)
                        
                        # Place order
                        with st.spinner("Placing BUY order..."):
                            kwargs = {}
                            if buy_quote:
                                kwargs["quote"] = buy_quote
                            
                            result = place_order_testnet(
                                exchange, symbol, "BUY", buy_type, 
                                qty=buy_qty, price=buy_price, **kwargs
                            )
                            
                            # Check if order was successful
                            if not result.get("success", False):
                                st.error(f"Order Failed: {result.get('error', 'Unknown error')}")
                            else:
                                # Format and display result
                                order_response = result.get("response", {})
                                formatted = format_order_response(order_response)
                                
                                st.success("BUY Order Placed Successfully!")
                                
                                # For market orders, fetch complete order details
                                order_id = formatted.get("order_id")
                                if order_id and buy_type == "MARKET":
                                    try:
                                        # Small delay to allow order to settle
                                        import time
                                        time.sleep(0.5)
                                        
                                        # Get complete order status
                                        status_result = order_status_testnet(exchange, symbol, order_id)
                                        if status_result.get("success"):
                                            complete_order = format_order_response({"order_response": status_result.get("order_status", {}), "latency_ms": 0})
                                            # Update formatted data with complete details
                                            for key, value in complete_order.items():
                                                if value is not None and value != "N/A":
                                                    formatted[key] = value
                                    except Exception as e:
                                        st.warning(f"Could not fetch complete order details: {str(e)}")
                                
                                # Debug: Show raw response
                                with st.expander("🔍 Debug: Raw API Response"):
                                    st.json(result)
                                
                                # Display order details
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    st.metric("Order ID", formatted.get("order_id", "N/A"))
                                    st.metric("Status", formatted.get("status", "N/A"))
                                with col_b:
                                    qty_display = formatted.get("quantity", "N/A")
                                    if formatted.get("executed_value") and qty_display == "N/A":
                                        qty_display = f"${formatted.get('executed_value')} USDT"
                                    st.metric("Quantity/Value", qty_display)
                                    st.metric("Latency", f"{formatted.get('latency_ms', 0):.1f} ms")
                                
                                # Show additional details if available
                                if formatted.get("avg_price"):
                                    st.info(f"**Avg Price**: ${formatted.get('avg_price'):,}")
                                if formatted.get("executed_value"):
                                    st.info(f"**Executed Value**: ${formatted.get('executed_value')} USDT")
                                
                                # Store order for later reference
                                st.session_state.placed_orders.append({
                                    "timestamp": datetime.now().isoformat(),
                                    "exchange": exchange,
                                    "symbol": symbol,
                                    "side": "BUY",
                                    "order_id": formatted.get("order_id"),
                                    "details": formatted
                                })
                            
                    except Exception as e:
                        error_msg = str(e)
                        
                        # Check for common testnet issues
                        if "insufficient balance" in error_msg.lower() or "170131" in error_msg:
                            st.error("❌ **Insufficient Testnet Balance**")
                            st.info("""
                            **Testnet Account Issue**: Your testnet account doesn't have enough fake USDT balance for this order.
                            
                            **Solutions**:
                            1. **Reduce order size** - Try a smaller quantity (e.g., 0.001 BTC instead of 7)
                            2. **Get testnet funds** - Visit your exchange's testnet faucet:
                               - Binance: https://testnet.binance.vision/
                               - Bybit: https://testnet.bybit.com/ (Account section)
                            3. **Use smaller amounts** - Testnet accounts have limited fake money
                            
                            **Current order**: {:.6f} BTCUSDT ≈ ${:,.0f} USDT needed
                            """.format(buy_qty or 0, (buy_qty or 0) * 100000))
                        else:
                            st.error(f"Failed to place BUY order: {error_msg}")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="trade-container sell-container">', unsafe_allow_html=True)
            st.markdown("** SELL ORDER**")
            
            # Order type selection outside form for reactivity
            sell_type = st.selectbox("Order Type", ["MARKET", "LIMIT"], key="sell_type")
            
            # Amount type selection outside form for MARKET orders (consistent with BUY side)
            if sell_type == "MARKET":
                sell_amount_type = st.radio("Amount Type", ["Quantity"], key="sell_amount", help="SELL orders typically use quantity")
            
            # Sell order form
            with st.form("sell_order_form"):
                if sell_type == "MARKET":
                    sell_qty = st.number_input("Quantity", min_value=0.000001, value=0.01, step=0.001, format="%.6f", key="sell_qty", help="Enter quantity > 0 (Try 0.01 for testing)")
                    sell_price = None
                    sell_quote = None
                else:  # LIMIT
                    sell_qty = st.number_input("Quantity", min_value=0.000001, value=0.01, step=0.001, format="%.6f", key="sell_qty_limit", help="Enter quantity > 0 (Try 0.01 for testing)")
                    sell_price = st.number_input("Price", min_value=0.01, value=105000.0, step=100.0, format="%.2f", key="sell_price", help="Enter price > 0 (Try current market price)")
                    sell_quote = None
                
                sell_submit = st.form_submit_button("Place SELL Order", type="primary")
                
                if sell_submit:
                    try:
                        # Additional validation for zero values
                        if sell_qty is None or sell_qty <= 0:
                            st.error("Please enter a valid quantity greater than 0")
                            st.stop()
                        if sell_type == "LIMIT" and (sell_price is None or sell_price <= 0):
                            st.error("Please enter a valid price greater than 0")
                            st.stop()
                        
                        # Validate parameters
                        validate_order_params("SELL", sell_type, sell_qty, sell_price, quote=sell_quote, exchange=exchange)
                        
                        # Place order
                        with st.spinner("Placing SELL order..."):
                            kwargs = {}
                            if sell_quote:
                                kwargs["quote"] = sell_quote
                            
                            result = place_order_testnet(
                                exchange, symbol, "SELL", sell_type,
                                qty=sell_qty, price=sell_price, **kwargs
                            )
                            
                            # Check if order was successful
                            if not result.get("success", False):
                                st.error(f"Order Failed: {result.get('error', 'Unknown error')}")
                            else:
                                # Format and display result
                                order_response = result.get("response", {})
                                formatted = format_order_response(order_response)
                                
                                st.success("SELL Order Placed Successfully!")
                                
                                # For market orders, fetch complete order details
                                order_id = formatted.get("order_id")
                                if order_id and sell_type == "MARKET":
                                    try:
                                        # Small delay to allow order to settle
                                        import time
                                        time.sleep(0.5)
                                        
                                        # Get complete order status
                                        status_result = order_status_testnet(exchange, symbol, order_id)
                                        if status_result.get("success"):
                                            complete_order = format_order_response({"order_response": status_result.get("order_status", {}), "latency_ms": 0})
                                            # Update formatted data with complete details
                                            for key, value in complete_order.items():
                                                if value is not None and value != "N/A":
                                                    formatted[key] = value
                                    except Exception as e:
                                        st.warning(f"Could not fetch complete order details: {str(e)}")
                                
                                # Debug: Show raw response
                                with st.expander("🔍 Debug: Raw API Response"):
                                    st.json(result)
                                
                                # Display order details
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    st.metric("Order ID", formatted.get("order_id", "N/A"))
                                    st.metric("Status", formatted.get("status", "N/A"))
                                with col_b:
                                    qty_display = formatted.get("quantity", "N/A")
                                    if formatted.get("executed_value") and qty_display == "N/A":
                                        qty_display = f"${formatted.get('executed_value')} USDT"
                                    st.metric("Quantity/Value", qty_display)
                                    st.metric("Latency", f"{formatted.get('latency_ms', 0):.1f} ms")
                                
                                # Show additional details if available
                                if formatted.get("avg_price"):
                                    st.info(f"**Avg Price**: ${formatted.get('avg_price'):,}")
                                if formatted.get("executed_value"):
                                    st.info(f"**Executed Value**: ${formatted.get('executed_value')} USDT")
                                
                                # Store order for later reference
                                st.session_state.placed_orders.append({
                                    "timestamp": datetime.now().isoformat(),
                                    "exchange": exchange,
                                    "symbol": symbol,
                                    "side": "SELL",
                                    "order_id": formatted.get("order_id"),
                                    "details": formatted
                                })
                            
                    except Exception as e:
                        error_msg = str(e)
                        
                        # Check for common testnet issues  
                        if "insufficient balance" in error_msg.lower() or "170131" in error_msg:
                            st.error("❌ **Insufficient Testnet Balance**")
                            st.info("""
                            **Testnet Account Issue**: Your testnet account doesn't have enough fake crypto balance for this SELL order.
                            
                            **Solutions**:
                            1. **Get testnet crypto** - Use the exchange's testnet faucet to get fake BTC/ETH
                            2. **Reduce order size** - Try a smaller quantity  
                            3. **Check balance** - Log into your testnet account to see available balances
                            
                            **Current order**: {:.6f} BTCUSDT
                            """.format(sell_qty or 0))
                        else:
                            st.error(f"Failed to place SELL order: {error_msg}")
            
            st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.subheader("Cancel Order")
    
    with st.form("cancel_order_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            cancel_symbol = st.text_input("Symbol", value=symbol, key="cancel_symbol")
        
        with col2:
            cancel_order_id = st.text_input("Order ID", help="Enter the order ID to cancel")
        
        cancel_submit = st.form_submit_button("Cancel Order", type="secondary")
        
        if cancel_submit:
            if not cancel_order_id:
                st.error("Please enter an order ID")
            else:
                try:
                    with st.spinner("Cancelling order..."):
                        result = cancel_order_testnet(exchange, cancel_symbol, cancel_order_id)
                        
                        st.success("Order Cancelled Successfully!")
                        st.json(result["cancel_response"])
                        
                except Exception as e:
                    st.error(f"Failed to cancel order: {str(e)}")

with tab3:
    st.subheader("Order Status")
    
    with st.form("status_order_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            status_symbol = st.text_input("Symbol", value=symbol, key="status_symbol")
        
        with col2:
            status_order_id = st.text_input("Order ID", help="Enter the order ID to check")
        
        status_submit = st.form_submit_button("🔍 Check Status", type="secondary")
        
        if status_submit:
            if not status_order_id:
                st.error("Please enter an order ID")
            else:
                try:
                    with st.spinner("Fetching order status..."):
                        result = order_status_testnet(exchange, status_symbol, status_order_id)
                        
                        if not result.get("success", False):
                            st.error(f"❌ Failed to get order status: {result.get('error', 'Unknown error')}")
                        else:
                            st.success("Order Status Retrieved!")
                            
                            # Display formatted status
                            status_data = result["order_status"]
                            
                            # Format the status data using the same function as order placement
                            formatted_status = format_order_response({"order_response": status_data, "latency_ms": 0})
                            
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Status", formatted_status.get("status", "N/A"))
                            with col2:
                                st.metric("Side", formatted_status.get("side", "N/A"))
                            with col3:
                                st.metric("Type", formatted_status.get("type", "N/A"))
                            
                            # Additional details
                            if formatted_status.get("quantity"):
                                st.info(f"**Quantity**: {formatted_status.get('quantity')}")
                            if formatted_status.get("price"):
                                st.info(f"**Price**: ${formatted_status.get('price')}")
                            if formatted_status.get("avg_price"):
                                st.info(f"**Average Price**: ${formatted_status.get('avg_price')}")
                            
                            # Raw status data
                            with st.expander("Raw Status Data"):
                                st.json(status_data)
                        
                except Exception as e:
                    st.error(f"Failed to get order status: {str(e)}")

with tab4:
    st.subheader("Position & PnL Monitor")
    st.info("Monitor the state and profitability of a position initiated by a filled order")
    
    with st.form("position_monitor_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            monitor_symbol = st.text_input("Symbol", value=symbol, key="monitor_symbol")
            monitor_order_id = st.text_input("Order ID", help="Enter order ID of filled order to monitor")
        
        with col2:
            st.markdown("**Position Information:**")
            st.markdown("- **connector_name**: Exchange")
            st.markdown("- **entry_price**: Average filled price")
            st.markdown("- **quantity**: Position size")
            st.markdown("- **NetPnL**: Real-time P&L calculation")
        
        monitor_submit = st.form_submit_button("Get Position Snapshot", type="primary")
        
        if monitor_submit:
            if not monitor_order_id:
                st.error("Please enter an order ID")
            else:
                try:
                    with st.spinner("Fetching position snapshot..."):
                        snapshot = get_position_snapshot(exchange, monitor_symbol, monitor_order_id)
                        
                        if "error" in snapshot:
                            st.error(f"Failed to get position: {snapshot['error']}")
                        else:
                            st.success("Position Snapshot Retrieved!")
                            
                            # Display position metrics
                            col1, col2, col3, col4 = st.columns(4)
                            
                            with col1:
                                st.metric("Exchange", snapshot.get("connector_name", "N/A"))
                                st.metric("Symbol", snapshot.get("pair_name", "N/A"))
                            
                            with col2:
                                entry_price = snapshot.get("entry_price")
                                if entry_price:
                                    st.metric("Entry Price", f"${entry_price:,.2f}")
                                else:
                                    st.metric("Entry Price", "N/A")
                                
                                current_price = snapshot.get("current_price")
                                if current_price:
                                    st.metric("Current Price", f"${current_price:,.2f}")
                                else:
                                    st.metric("Current Price", "N/A")
                            
                            with col3:
                                quantity = snapshot.get("quantity")
                                if quantity:
                                    st.metric("Quantity", f"{quantity:.6f}")
                                else:
                                    st.metric("Quantity", "N/A")
                                
                                position_side = snapshot.get("position_side", "N/A").title()
                                st.metric("Position Side", position_side)
                            
                            with col4:
                                net_pnl = snapshot.get("NetPnL")
                                if net_pnl is not None:
                                    color = "🟢" if net_pnl >= 0 else "🔴"
                                    # Use more decimal places for small PnL values
                                    if abs(net_pnl) < 0.01:
                                        st.metric("Net PnL", f"{color} ${net_pnl:.4f}")
                                    else:
                                        st.metric("Net PnL", f"{color} ${net_pnl:,.2f}")
                                else:
                                    st.metric("Net PnL", "N/A")
                                
                                unrealized_pnl = snapshot.get("unrealized_pnl")
                                if unrealized_pnl is not None:
                                    color = "🟢" if unrealized_pnl >= 0 else "🔴"
                                    # Use more decimal places for small PnL values
                                    if abs(unrealized_pnl) < 0.01:
                                        st.metric("Unrealized PnL", f"{color} ${unrealized_pnl:.4f}")
                                    else:
                                        st.metric("Unrealized PnL", f"{color} ${unrealized_pnl:,.2f}")
                                else:
                                    st.metric("Unrealized PnL", "N/A")
                            
                            # Entry timestamp
                            entry_time = snapshot.get("entry_timestamp")
                            if entry_time:
                                st.info(f"**Entry Time:** {entry_time}")
                            
                            # Raw snapshot data
                            with st.expander("🔍 Raw Position Data"):
                                st.json(snapshot)
                
                except Exception as e:
                    st.error(f"Failed to get position snapshot: {str(e)}")

with tab5:
    st.subheader("Performance Test")
    st.info("Test the system's ability to handle rapid order execution (200 orders in 5 minutes)")
    
    with st.form("performance_test_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            perf_symbol = st.text_input("Symbol", value=symbol, key="perf_symbol")
            perf_count = st.number_input("Number of Orders", min_value=1, max_value=50, value=10, 
                                       help="Number of test orders to place (max 50 for safety)")
        
        with col2:
            perf_duration = st.number_input("Duration (seconds)", min_value=30, max_value=300, value=60,
                                          help="Maximum time to run the test")
            
            st.markdown("**Test Process:**")
            st.markdown("1. Place LIMIT orders away from market")
            st.markdown("2. Immediately attempt to cancel each order")
            st.markdown("3. Log success/failure rates and latency")
        
        perf_submit = st.form_submit_button("🚀 Start Performance Test", type="primary")
        
        if perf_submit:
            try:
                with st.spinner(f"Running performance test ({perf_count} orders, max {perf_duration}s)..."):
                    results = performance_test_testnet(exchange, perf_symbol, perf_count, perf_duration)
                    
                    if "error" in results:
                        st.error(f"Performance test failed: {results['error']}")
                    else:
                        st.success("Performance Test Completed!")
                        
                        # Display summary metrics
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.metric("Total Orders", results.get("total_orders", 0))
                            st.metric("Successful Orders", results.get("successful_orders", 0))
                        
                        with col2:
                            success_rate = results.get("success_rate", 0)
                            st.metric("Success Rate", f"{success_rate:.1f}%")
                            
                            cancel_rate = results.get("cancel_rate", 0) 
                            st.metric("Cancel Rate", f"{cancel_rate:.1f}%")
                        
                        with col3:
                            avg_place = results.get("avg_place_latency", 0)
                            st.metric("Avg Place Latency", f"{avg_place:.1f} ms")
                            
                            avg_cancel = results.get("avg_cancel_latency", 0)
                            st.metric("Avg Cancel Latency", f"{avg_cancel:.1f} ms")
                        
                        with col4:
                            duration = results.get("duration", 0)
                            st.metric("Test Duration", f"{duration:.1f}s")
                            
                            throughput = results.get("total_orders", 0) / max(duration, 1)
                            st.metric("Throughput", f"{throughput:.1f} orders/s")
                        
                        # Detailed results
                        orders = results.get("orders", [])
                        if orders:
                            st.subheader("Order Details")
                            
                            # Show summary stats
                            successful_orders = [o for o in orders if o.get("status") == "cancelled"]
                            failed_orders = [o for o in orders if "error" in o or o.get("status") == "place_failed"]
                            
                            if successful_orders:
                                st.success(f"✅ {len(successful_orders)} orders placed and cancelled successfully")
                            
                            if failed_orders:
                                st.error(f"❌ {len(failed_orders)} orders failed")
                                
                                # Show failed order details
                                with st.expander("Failed Orders"):
                                    for i, order in enumerate(failed_orders):
                                        st.write(f"**Order {i+1}:** {order.get('error', 'Unknown error')}")
                        
                        # Raw results
                        with st.expander("🔍 Raw Performance Data"):
                            st.json(results)
            
            except Exception as e:
                st.error(f"Performance test failed: {str(e)}")

# Recent orders section
if st.session_state.placed_orders:
    st.subheader(" Recent Orders")
    
    # Display recent orders in a table
    recent_orders = st.session_state.placed_orders[-10:]  # Last 10 orders
    
    for i, order in enumerate(reversed(recent_orders)):
        with st.expander(f"{order['side']} {order['symbol']} - {order['order_id']} ({order['timestamp'][:19]})"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown(f"**Exchange:** {order['exchange'].upper()}")
                st.markdown(f"**Symbol:** {order['symbol']}")
                st.markdown(f"**Side:** {order['side']}")
            
            with col2:
                details = order['details']
                st.markdown(f"**Order ID:** {details.get('order_id', 'N/A')}")
                st.markdown(f"**Status:** {details.get('status', 'N/A')}")
                st.markdown(f"**Type:** {details.get('type', 'N/A')}")
            
            with col3:
                st.markdown(f"**Quantity:** {details.get('quantity', 'N/A')}")
                # Show avg_price for filled orders, otherwise show price
                price_display = details.get('price', 'N/A')
                if details.get('avg_price') and details.get('status') in ['FILLED', 'Filled', 'PARTIALLY_FILLED']:
                    price_display = f"${details.get('avg_price'):.2f}"
                elif price_display != 'N/A' and price_display is not None:
                    try:
                        price_display = f"${float(price_display):.2f}"
                    except:
                        pass
                st.markdown(f"**Price:** {price_display}")
                st.markdown(f"**Latency:** {details.get('latency_ms', 0):.1f} ms")
            
            # Quick action buttons
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(f"Check Status", key=f"status_{i}"):
                    try:
                        result = order_status_testnet(order['exchange'], order['symbol'], str(order['order_id']))
                        st.json(result["order_status"])
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
            
            with col_b:
                if st.button(f"Cancel Order", key=f"cancel_{i}"):
                    try:
                        result = cancel_order_testnet(order['exchange'], order['symbol'], str(order['order_id']))
                        st.success("Order cancelled!")
                        st.json(result["cancel_response"])
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

# Help and safety reminders
with st.expander(" Trading Help & Safety"):
    st.markdown("""
    ** TESTNET SAFETY:**
    - This interface **ONLY** works with testnet environments
    - All trades use **FAKE MONEY** - no real funds at risk
    - Perfect for learning and testing trading strategies
    
    ** Supported Operations:**
    - **Place Orders:** LIMIT and MARKET orders on testnet
    - **Cancel Orders:** Cancel pending orders by ID
    - **Order Status:** Check execution status and details
    - **Position Monitor:** Real-time PnL tracking for filled orders
    - **Performance Test:** Stress test with rapid order execution
    
    ** Testnet Exchanges:**
    - **Binance Testnet:** https://testnet.binance.vision/
    - **Bybit Testnet:** https://testnet.bybit.com/
    - **Deribit Testnet:** https://test.deribit.com/
    
    **Order Types:**
    - **MARKET:** Execute immediately at best available price
    - **LIMIT:** Execute only at specified price or better
    
    **Position Monitoring:**
    - Track live PnL for filled orders
    - Real-time price updates and profit/loss calculation
    - Structured position data with entry price, quantity, and side
    
    **Performance Testing:**
    - Stress test system with rapid order placement/cancellation
    - Measure success rates and latency statistics
    - Configurable test parameters (count and duration)
    
    **Tips:**
    - Start with small test orders to learn the interface
    - Use Position Monitor to track filled orders
    - Run Performance Tests to validate system reliability
    - Check order status after placement
    - Save order IDs for later reference
    
    ** CLI Equivalent:**
    ```bash
    # Place order
    python TASK2.3.4/2.1.py --exch {exchange} --testnet place {symbol} --side BUY --type LIMIT --qty 0.001 --price 50000
    
    # Cancel order  
    python TASK2.3.4/2.1.py --exch {exchange} --testnet cancel {symbol} --order-id 12345
    
    # Check status
    python TASK2.3.4/2.1.py --exch {exchange} --testnet status {symbol} --order-id 12345
    
    # Monitor position
    python TASK2.3.4/2.1.py --exch {exchange} --testnet monitor {symbol} --order-id 12345
    
    # Performance test
    python TASK2.3.4/2.1.py --exch {exchange} --testnet perftest {symbol} --count 50 --duration 120
    ```
    """)

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666;">
    <p><strong>TESTNET ENVIRONMENT</strong> - No real money involved</p>
    <p>Real-time order management with production-grade APIs</p>
</div>
""", unsafe_allow_html=True)
