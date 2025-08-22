"""
Order Book Page - L2 order book depth analysis and market structure

Powered by TASK1/1.2.py
"""
import streamlit as st
import asyncio
import pandas as pd
from datetime import datetime
import sys
from pathlib import Path

# Add webapp to path
webapp_root = Path(__file__).parent.parent
sys.path.insert(0, str(webapp_root))

try:
    from core.orderbook import get_l2_orderbook, get_book_summary, get_supported_exchanges
    from utils.env import get_secret
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.stop()

def format_timestamp(timestamp):
    """Format timestamp for display"""
    if not timestamp:
        return "N/A"
    
    try:
        # Handle both string and numeric timestamps
        if isinstance(timestamp, str):
            # Try parsing ISO format first
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
            except:
                return timestamp
        elif isinstance(timestamp, (int, float)):
            # Handle Unix timestamps (both seconds and milliseconds)
            if timestamp > 1e12:  # Milliseconds
                timestamp = timestamp / 1000
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            return str(timestamp)
    except Exception:
        return str(timestamp)

def display_orderbook_analysis(exchange, orderbook, top_n, show_raw):
    """Display order book analysis for a single exchange"""
    
    # Summary metrics
    st.subheader(f"{exchange.upper()} Market Summary")

    # First row - main price metrics
    col1, col2, col3 = st.columns(3)

    with col1:
        bid_value = orderbook['best_bid']
        if bid_value and bid_value >= 1:
            bid_str = f"${bid_value:.2f}"
        elif bid_value:
            bid_str = f"${bid_value:.6f}"
        else:
            bid_str = "N/A"
        st.metric("Best Bid", bid_str)

    with col2:
        ask_value = orderbook['best_ask']
        if ask_value and ask_value >= 1:
            ask_str = f"${ask_value:.2f}"
        elif ask_value:
            ask_str = f"${ask_value:.6f}"
        else:
            ask_str = "N/A"
        st.metric("Best Ask", ask_str)

    with col3:
        mid_value = orderbook['mid']
        if mid_value and mid_value >= 1:
            mid_str = f"${mid_value:.2f}"
        elif mid_value:
            mid_str = f"${mid_value:.6f}"
        else:
            mid_str = "N/A"
        st.metric("Mid Price", mid_str)

    # Second row - spread and levels
    col4, col5, col6 = st.columns(3)

    with col4:
        spread_value = orderbook.get('spread')
        if spread_value and spread_value >= 0.01:
            spread_str = f"${spread_value:.4f}"
        elif spread_value:
            spread_str = f"${spread_value:.8f}"
        else:
            spread_str = "N/A"
        st.metric("Spread", spread_str)

    with col5:
        spread_bps = orderbook.get('spread_bps')
        if spread_bps is not None:
            st.metric("Spread (bps)", f"{spread_bps:.4f}")
        else:
            st.metric("Spread (bps)", "N/A")

    with col6:
        levels_info = f"B:{orderbook['bid_count']} / A:{orderbook['ask_count']}"
        st.metric(
            "Levels (B/A)",
            levels_info
        )

    # Order book visualization
    st.subheader(f"Order Book Depth - Top {top_n} Levels")

    if orderbook['bids'] and orderbook['asks']:
        # Get top levels
        top_bids = orderbook['bids'][:top_n]
        top_asks = orderbook['asks'][:top_n]
        
        # Create side-by-side display
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**BIDS (Buy Orders)**")
            
            bid_data = []
            cumulative_qty = 0
            for price, qty in top_bids:
                cumulative_qty += qty
                bid_data.append({
                    "Price": f"${price:.6f}",
                    "Quantity": f"{qty:.6f}",
                    "Cumulative": f"{cumulative_qty:.6f}",
                    "Total Value": f"${price * cumulative_qty:.2f}"
                })
            
            if bid_data:
                df_bids = pd.DataFrame(bid_data)
                st.dataframe(df_bids, use_container_width=True, hide_index=True)
        
        with col2:
            st.markdown("**ASKS (Sell Orders)**")
            
            ask_data = []
            cumulative_qty = 0
            for price, qty in top_asks:
                cumulative_qty += qty
                ask_data.append({
                    "Price": f"${price:.6f}",
                    "Quantity": f"{qty:.6f}",
                    "Cumulative": f"{cumulative_qty:.6f}",
                    "Total Value": f"${price * cumulative_qty:.2f}"
                })
            
            if ask_data:
                df_asks = pd.DataFrame(ask_data)
                st.dataframe(df_asks, use_container_width=True, hide_index=True)

    # Volume analysis
    st.subheader("Volume Analysis")

    if orderbook['bids'] and orderbook['asks']:
        summary = get_book_summary(orderbook, top_n)
        
        if summary.get('bid_volumes') and summary.get('ask_volumes'):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Cumulative Bid Volumes**")
                bid_vol_data = []
                for level, volume in summary['bid_volumes'].items():
                    level_num = level.replace('top_', '')
                    bid_vol_data.append({
                        "Top Levels": level_num,
                        "Cumulative Quantity": f"{volume:.6f}",
                        "Avg Price": f"${sum(p * q for p, q in orderbook['bids'][:int(level_num)]) / volume:.6f}" if volume > 0 else "N/A"
                    })
                
                if bid_vol_data:
                    df_bid_vol = pd.DataFrame(bid_vol_data)
                    st.dataframe(df_bid_vol, use_container_width=True, hide_index=True)
            
            with col2:
                st.markdown("**Cumulative Ask Volumes**")
                ask_vol_data = []
                for level, volume in summary['ask_volumes'].items():
                    level_num = level.replace('top_', '')
                    ask_vol_data.append({
                        "Top Levels": level_num,
                        "Cumulative Quantity": f"{volume:.6f}",
                        "Avg Price": f"${sum(p * q for p, q in orderbook['asks'][:int(level_num)]) / volume:.6f}" if volume > 0 else "N/A"
                    })
                
                if ask_vol_data:
                    df_ask_vol = pd.DataFrame(ask_vol_data)
                    st.dataframe(df_ask_vol, use_container_width=True, hide_index=True)

    # Market depth visualization
    if len(orderbook['bids']) >= 10 and len(orderbook['asks']) >= 10:
        st.subheader("Market Depth Visualization")
        
        # Prepare data for chart
        bid_prices = [p for p, q in orderbook['bids'][:20]]
        bid_qtys = [q for p, q in orderbook['bids'][:20]]
        ask_prices = [p for p, q in orderbook['asks'][:20]]
        ask_qtys = [q for p, q in orderbook['asks'][:20]]
        
        # Create DataFrame for plotting
        chart_data = pd.DataFrame({
            'Price': bid_prices + ask_prices,
            'Quantity': bid_qtys + ask_qtys,
            'Side': ['Bid'] * len(bid_prices) + ['Ask'] * len(ask_prices)
        })
        
        # Display chart
        st.bar_chart(
            chart_data.set_index('Price')['Quantity'],
            height=400
        )

    # Exchange-specific information
    st.subheader("Exchange Information")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(f"**Exchange:** {exchange.upper()}")
        st.markdown(f"**Symbol:** {orderbook['symbol']}")

    with col2:
        st.markdown(f"**Bid Levels:** {orderbook['bid_count']}")
        st.markdown(f"**Ask Levels:** {orderbook['ask_count']}")

    with col3:
        if orderbook.get('timestamp'):
            formatted_ts = format_timestamp(orderbook['timestamp'])
            st.markdown(f"**Exchange Timestamp:** {formatted_ts}")

    # Raw data section
    if show_raw and orderbook:
        st.subheader("Raw Data")
        with st.expander("Show JSON Response"):
            # Truncate large arrays for display
            display_data = orderbook.copy()
            if len(display_data.get('bids', [])) > 20:
                display_data['bids'] = display_data['bids'][:20] + [f"... and {len(orderbook['bids']) - 20} more levels"]
            if len(display_data.get('asks', [])) > 20:
                display_data['asks'] = display_data['asks'][:20] + [f"... and {len(orderbook['asks']) - 20} more levels"]
            
            st.json(display_data)

# Page configuration
st.set_page_config(
    page_title="Order Book - Crypto Tools",
    page_icon="📊",
    layout="wide"
)

# Header
st.title("Order Book Analyzer")
st.markdown("*L2 order book depth analysis and market structure*")
st.caption("Powered by TASK1/1.2.py")

# Sidebar controls
st.sidebar.header("Controls")

# Symbol input
symbol = st.sidebar.text_input(
    "Trading Pair",
    value="BTCUSDT",
    help="Enter symbol in exchange-specific format"
).strip().upper()

# Exchange selection (multiple with all selected by default except OKX)
available_exchanges = get_supported_exchanges()
default_exchanges = [exch for exch in available_exchanges if exch.lower() != "okx"]
selected_exchanges = st.sidebar.multiselect(
    "Select Exchanges",
    options=available_exchanges,
    default=default_exchanges,  # Select all exchanges except OKX by default
    key="orderbook_exchanges",  # Unique key to avoid caching issues
    help="Choose which exchanges to fetch order books from"
)

# Depth settings
limit = st.sidebar.slider(
    "Book Depth Limit",
    min_value=10,
    max_value=1000,
    value=200,
    step=10,
    help="Maximum number of price levels to fetch"
)

top_n = st.sidebar.slider(
    "Top Levels to Display",
    min_value=5,
    max_value=50,
    value=10,
    help="Number of top bid/ask levels to show in detail"
)

# Refresh button
if st.sidebar.button("Fetch Order Books", type="primary"):
    st.rerun()

# Show raw data toggle
show_raw = st.sidebar.checkbox("Show Raw Data", value=False)

# Main content
if not symbol:
    st.warning("Please enter a trading pair symbol")
    st.stop()

if not selected_exchanges:
    st.warning("Please select at least one exchange")
    st.stop()

# Fetch order book data from multiple exchanges
async def fetch_all_orderbooks():
    """Fetch order book data from all selected exchanges"""
    results = {}
    
    for exchange in selected_exchanges:
        try:
            with st.spinner(f"Fetching L2 order book for {symbol} from {exchange}..."):
                result = await get_l2_orderbook(exchange, symbol, limit)
                if result:
                    results[exchange] = result
        except Exception as e:
            st.warning(f"Error fetching from {exchange}: {str(e)}")
            continue
    
    return results

# Fetch data
try:
    orderbooks = asyncio.run(fetch_all_orderbooks())
except Exception as e:
    st.error(f"Failed to fetch order books: {str(e)}")
    st.stop()

if not orderbooks:
    st.warning("No order book data received from any exchange. Check symbol format and exchange availability.")
    st.stop()

# Display results
st.markdown(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
st.markdown(f"**Fetched from {len(orderbooks)} exchange(s):** {', '.join(orderbooks.keys())}")

# Create tabs for each exchange
if len(orderbooks) > 1:
    tabs = st.tabs([f"{exchange.upper()}" for exchange in orderbooks.keys()])
    
    for i, (exchange, orderbook) in enumerate(orderbooks.items()):
        with tabs[i]:
            display_orderbook_analysis(exchange, orderbook, top_n, show_raw)
else:
    # Single exchange display
    exchange, orderbook = list(orderbooks.items())[0]
    display_orderbook_analysis(exchange, orderbook, top_n, show_raw)

# Help section
with st.expander("Help & Usage"):
    st.markdown("""
    **Order Book Analysis:**
    
    **Key Metrics:**
    - **Best Bid/Ask:** Highest bid and lowest ask prices
    - **Mid Price:** Average of best bid and ask
    - **Spread:** Difference between best ask and bid
    - **Spread (bps):** Spread as basis points (1 bps = 0.01%)
    
    **Order Book Structure:**
    - **Bids (Green):** Buy orders, highest prices first
    - **Asks (Red):** Sell orders, lowest prices first
    - **Cumulative:** Running total of quantities
    - **Total Value:** Cumulative quantity × price
    
    **Volume Analysis:**
    - Shows cumulative volumes at different depth levels
    - Useful for understanding market liquidity
    - Average prices show weighted execution costs
    
    **Multi-Exchange Comparison:**
    - Select multiple exchanges to compare order books
    - Each exchange gets its own tab for detailed analysis
    - Default selection includes all available exchanges
    
    **Symbol Formats:**
    - Each exchange has specific symbol conventions
    - Check the CLI tool for supported formats: `python TASK1/1.2.py --help`
    
    **Data Freshness:**
    - Order books are fetched in real-time
    - Use refresh button to get latest data
    - For live streaming, use the CLI tool with `--ws` flag
    """)

# Footer
st.markdown("---")
st.caption("Order book data sourced from exchange APIs. Prices update in real-time.")
st.caption("For WebSocket streaming, use: `python TASK1/1.2.py {symbol} --exch {exchange} --ws`")
