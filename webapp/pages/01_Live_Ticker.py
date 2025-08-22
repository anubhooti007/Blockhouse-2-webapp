"""
Live Ticker Page - Real-time price comparison across exchanges

Powered by TASK1/1.1.py
"""
import streamlit as st
import asyncio
import pandas as pd
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

# Add webapp to path
webapp_root = Path(__file__).parent.parent
sys.path.insert(0, str(webapp_root))

try:
    from core.ticker import get_multi_best_bid_ask, get_aggregated_best, get_supported_exchanges
    from utils.env import get_secret
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.stop()

def format_timestamp(timestamp_ms):
    """Convert Unix timestamp in milliseconds to UTC datetime string"""
    if not timestamp_ms or timestamp_ms == "N/A":
        return "N/A"
    try:
        # Convert milliseconds to seconds
        timestamp_seconds = timestamp_ms / 1000
        # Create datetime object in UTC
        dt = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
        # Format as readable string
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, TypeError):
        return "Invalid"

# Page configuration
st.set_page_config(
    page_title="Live Ticker - Crypto Tools",
    page_icon="�",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .metric-container {
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #333;
        margin: 0.5rem 0;
    }
    .exchange-header {
        font-weight: bold;
        color: #00f5ff;
        font-size: 1.2rem;
    }
    .price-positive { color: #00ff88; }
    .price-negative { color: #ff6b6b; }
    .spread-info { 
        font-size: 0.9rem; 
        color: #888; 
    }
</style>
""", unsafe_allow_html=True)

# Header
st.title("Live Ticker")
st.markdown("*Real-time best bid/ask prices across multiple exchanges*")
st.caption("Powered by TASK1/1.1.py")

# Sidebar controls
st.sidebar.header("Controls")

# Symbol input
symbol = st.sidebar.text_input(
    "Trading Pair",
    value="BTCUSDT",
    help="Enter symbol in any format: BTCUSDT, BTC-USDT, BTC/USDT"
).strip().upper()

# Exchange selection
available_exchanges = get_supported_exchanges()
selected_exchanges = st.sidebar.multiselect(
    "Select Exchanges",
    options=available_exchanges,
    default=available_exchanges,  # Select all exchanges by default
    help="Choose which exchanges to query"
)

# Refresh settings
auto_refresh = st.sidebar.checkbox("Auto Refresh", value=False)
refresh_interval = st.sidebar.slider(
    "Refresh Interval (seconds)",
    min_value=5,
    max_value=60,
    value=10,
    help="How often to update prices"
)

# Manual refresh button
if st.sidebar.button("🔄 Refresh Now", type="primary"):
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

# Create placeholder for dynamic updates
placeholder = st.empty()

async def fetch_ticker_data():
    """Fetch ticker data from selected exchanges"""
    try:
        with st.spinner(f"Fetching prices for {symbol} from {len(selected_exchanges)} exchanges..."):
            results = await get_multi_best_bid_ask(selected_exchanges, symbol)
            return results
    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        return []

# Fetch data
try:
    results = asyncio.run(fetch_ticker_data())
except Exception as e:
    st.error(f"Failed to fetch ticker data: {str(e)}")
    st.stop()

if not results:
    st.warning("No data received. Check symbol format and exchange availability.")
    st.stop()

with placeholder.container():
    # Current timestamp
    st.markdown(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Summary metrics
    if len(results) > 1:
        aggregated = get_aggregated_best(results)
        
        if aggregated.get("spot"):
            st.subheader("Spot Markets Summary")
            spot = aggregated["spot"]
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(
                    "Best Bid",
                    f"${spot['best_bid']:.2f}",
                    help=f"Best bid on {spot['best_bid_exchange']}"
                )
            
            with col2:
                st.metric(
                    "Best Ask", 
                    f"${spot['best_ask']:.2f}",
                    help=f"Best ask on {spot['best_ask_exchange']}"
                )
            
            with col3:
                st.metric(
                    "Mid Price",
                    f"${spot['mid']:.2f}"
                )
            
            with col4:
                st.metric(
                    "Cross-Exchange Spread",
                    f"{spot['spread_bps']:.1f} bps"
                )
        
        if aggregated.get("perpetual"):
            st.subheader("🔄 Perpetual Futures Summary")
            perp = aggregated["perpetual"]
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(
                    "Best Bid",
                    f"${perp['best_bid']:.2f}",
                    help=f"Best bid on {perp['best_bid_exchange']}"
                )
            
            with col2:
                st.metric(
                    "Best Ask",
                    f"${perp['best_ask']:.2f}",
                    help=f"Best ask on {perp['best_ask_exchange']}"
                )
            
            with col3:
                st.metric(
                    "Mid Price",
                    f"${perp['mid']:.2f}"
                )
            
            with col4:
                st.metric(
                    "Cross-Exchange Spread",
                    f"{perp['spread_bps']:.1f} bps"
                )
    
    # Individual exchange results
    st.subheader("Exchange Details")
    
    # Create DataFrame for tabular display
    df_data = []
    for result in results:
        df_data.append({
            "Exchange": result["exchange"].upper(),
            "Symbol": result["raw_symbol"],
            "Bid": result["bid"],
            "Ask": result["ask"],
            "Mid": result["mid"],
            "Spread (bps)": result["spread_bps"],
            "Timestamp": result.get("timestamp", "N/A")
        })
    
    df = pd.DataFrame(df_data)
    
    # Format the DataFrame
    if not df.empty:
        # Format numeric columns
        df["Bid"] = df["Bid"].apply(lambda x: f"${x:.6f}")
        df["Ask"] = df["Ask"].apply(lambda x: f"${x:.6f}")
        df["Mid"] = df["Mid"].apply(lambda x: f"${x:.6f}")
        df["Spread (bps)"] = df["Spread (bps)"].apply(lambda x: f"{x:.2f}")
        # Format timestamp column
        df["Timestamp"] = df["Timestamp"].apply(format_timestamp)
        
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )
    
    # Individual exchange cards
    st.subheader("🏢 Exchange Breakdown")
    
    cols = st.columns(min(len(results), 3))
    
    for i, result in enumerate(results):
        with cols[i % 3]:
            with st.container():
                st.markdown(f"**{result['exchange'].upper()}**")
                st.markdown(f"Symbol: `{result['raw_symbol']}`")
                st.markdown(f"Bid: **${result['bid']:.6f}**")
                st.markdown(f"Ask: **${result['ask']:.6f}**")
                st.markdown(f"Mid: **${result['mid']:.6f}**")
                st.markdown(f"Spread: {result['spread_bps']:.2f} bps")
                
                if result.get("timestamp"):
                    # Show formatted timestamp
                    formatted_time = format_timestamp(result["timestamp"])
                    st.caption(f"Time: {formatted_time}")
                    
                    # Calculate and show age
                    try:
                        age_seconds = (time.time() * 1000 - result["timestamp"]) / 1000
                        st.caption(f"Age: {age_seconds:.1f}s")
                    except (TypeError, ValueError):
                        st.caption("Age: Unknown")

# Raw data section
if show_raw and results:
    st.subheader("🔍 Raw Data")
    with st.expander("Show JSON Response"):
        st.json(results)

# Auto-refresh functionality
if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()

# Help section
with st.expander("Help & Usage"):
    st.markdown("""
    **Symbol Formats Supported:**
    - Standard: `BTCUSDT`, `ETHUSDT`
    - Hyphenated: `BTC-USDT`, `ETH-USDT`
    - Slash: `BTC/USDT`, `ETH/USDT`
    - Deribit perpetuals: `BTC-PERPETUAL`
    
    **Exchange Coverage:**
    - **Binance:** Spot trading pairs
    - **KuCoin:** Spot trading pairs  
    - **Deribit:** Perpetual futures
    - **BitMart:** Spot trading pairs
    - **OKX:** Spot trading pairs (geo-restricted)
    - **Hyperliquid:** Perpetual futures
    
    **Features:**
    - Real-time price comparison
    - Cross-exchange spread analysis
    - Auto-refresh capabilities
    - Multiple symbol format support
    
    **Tips:**
    - Use auto-refresh for live monitoring
    - Check individual exchange details for symbol mapping
    - Deribit shows perpetual futures prices
    - Cross-exchange spreads indicate arbitrage opportunities
    """)

# Footer
st.markdown("---")
st.caption("Data sourced from exchange APIs. Prices may have slight delays.")
st.caption("For high-frequency trading, use the CLI tools directly: `python TASK1/1.1.py`")
