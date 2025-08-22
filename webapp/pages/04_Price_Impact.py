"""
Price Impact Page - Order book walking and execution cost analysis

Powered by TASK1/1.4.py
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
    from core.impact import (
        estimate_price_impact, get_multi_impact, compare_impacts, 
        get_depth_summary, get_supported_exchanges
    )
    from utils.env import get_secret
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.stop()

# Page configuration
st.set_page_config(
    page_title="Price Impact - Crypto Tools",
    page_icon="�", 
    layout="wide"
)

# Header
st.title("Price Impact Analyzer")
st.markdown("*Order book walking and execution cost simulation*")
st.caption("Powered by TASK1/1.4.py")

# Sidebar controls
st.sidebar.header("Trade Parameters")

# Symbol input
symbol = st.sidebar.text_input(
    "Trading Pair",
    value="BTCUSDT",
    help="Enter trading pair symbol"
).strip().upper()

# Trade side
side = st.sidebar.selectbox(
    "Trade Side",
    options=["buy", "sell"],
    help="Direction of the trade"
)

# Notional amount
notional = st.sidebar.number_input(
    "Notional Amount (USDT)",
    min_value=100.0,
    max_value=1000000.0,
    value=10000.0,
    step=1000.0,
    help="Total USD value to trade"
)

# Exchange selection
st.sidebar.header(" Exchange Selection")

available_exchanges = get_supported_exchanges()

# Multi-exchange or single exchange
analysis_mode = st.sidebar.radio(
    "Analysis Mode",
    options=["Single Exchange", "Multi-Exchange Comparison"],
    help="Compare across exchanges or analyze single exchange"
)

if analysis_mode == "Single Exchange":
    exchange = st.sidebar.selectbox(
        "Select Exchange",
        options=available_exchanges,
        help="Choose exchange to analyze"
    )
    selected_exchanges = [exchange]
else:
    selected_exchanges = st.sidebar.multiselect(
        "Select Exchanges",
        options=available_exchanges,
        default=["binance", "bybit", "kucoin"],
        help="Choose exchanges to compare"
    )

# Depth settings
st.sidebar.header("Analysis Settings")

depth_limit = st.sidebar.slider(
    "Order Book Depth",
    min_value=50,
    max_value=1000,
    value=200,
    step=50,
    help="Maximum order book levels to fetch"
)

# Refresh button
if st.sidebar.button(" Analyze Impact", type="primary"):
    st.rerun()

# Show raw data toggle
show_raw = st.sidebar.checkbox("Show Raw Data", value=False)

# Helper function for dynamic impact formatting
def format_impact_bps(impact_bps):
    """Format impact with appropriate precision based on magnitude"""
    if impact_bps is None:
        return "N/A"
    if abs(impact_bps) < 0.001:
        return f"{impact_bps:.6f}"
    elif abs(impact_bps) < 0.01:
        return f"{impact_bps:.4f}"
    elif abs(impact_bps) < 1:
        return f"{impact_bps:.3f}"
    else:
        return f"{impact_bps:.2f}"

# Main content
if not symbol:
    st.warning("Please enter a trading pair symbol")
    st.stop()

if not selected_exchanges:
    st.warning("Please select at least one exchange")
    st.stop()

# Display trade summary
st.subheader("Trade Summary")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Symbol", symbol)

with col2:
    st.metric("Side", side.upper())

with col3:
    st.metric("Notional", f"${notional:,.0f}")

with col4:
    st.metric("Exchanges", len(selected_exchanges))

# Fetch impact data
async def fetch_impact_data():
    """Fetch price impact data from selected exchanges"""
    try:
        with st.spinner(f"Analyzing price impact for ${notional:,.0f} {side} of {symbol}..."):
            if analysis_mode == "Single Exchange":
                result = await estimate_price_impact(selected_exchanges[0], symbol, side, notional, depth_limit)
                return [result]
            else:
                results = await get_multi_impact(selected_exchanges, symbol, side, notional, depth_limit)
                return results
    except Exception as e:
        st.error(f"Error analyzing price impact: {str(e)}")
        return []

# Fetch data
try:
    impact_results = asyncio.run(fetch_impact_data())
except Exception as e:
    st.error(f"Failed to analyze price impact: {str(e)}")
    st.stop()

if not impact_results:
    st.warning("No impact data received. Check symbol format and exchange availability.")
    st.stop()

# Display results
st.markdown(f"**Analysis Completed:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")

# Multi-exchange comparison
if analysis_mode == "Multi-Exchange Comparison" and len(impact_results) > 1:
    st.subheader("Best Execution Comparison")
    
    comparison = compare_impacts(impact_results)
    
    if comparison and not comparison.get("error"):
        # Use a more compact display format
        st.markdown("### Summary")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"**Best Exchange:** {comparison['best_exchange'].upper()}")
            st.markdown(f"**Best Avg Price:** ${comparison['best_avg_exec']:.2f}")
        
        with col2:
            st.markdown(f"**Best Impact:** {format_impact_bps(comparison['best_impact_bps'])} bps")
            st.markdown(f"**Fillable:** {comparison['fillable_exchanges']}/{comparison['total_exchanges']} exchanges")
        
        with col3:
            st.markdown(f"**Price Spread:** ${comparison['avg_exec_spread']:.2f}")
            st.markdown(f"**Impact Range:** {format_impact_bps(comparison.get('max_impact_bps', 0) - comparison.get('min_impact_bps', 0))} bps")

# Individual exchange results
st.subheader("Exchange Analysis")

# Create summary table
df_data = []
for result in impact_results:
    fillable = "Yes" if result.get("filled", False) else "No"
    
    df_data.append({
        "Exchange": result["exchange"].upper(),
        "Mid Price": f"${result['mid']:.6f}" if result.get('mid') else "N/A",
        "Avg Execution": f"${result['avg_exec']:.6f}" if result.get('avg_exec') else "N/A",
        "Impact (bps)": format_impact_bps(result.get('impact_bps')),
        "Levels Touched": result.get('levels_touched', 'N/A'),
        "Filled Quantity": f"{result['filled_qty']:.6f}" if result.get('filled_qty') else "N/A",
        "Fillable": fillable
    })

if df_data:
    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

# Detailed exchange breakdown
st.subheader(" Detailed Analysis")

for result in impact_results:
    with st.expander(f"{result['exchange'].upper()} - Detailed Breakdown"):
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("**Market Data**")
            st.markdown(f"Best Bid: ${result['best_bid']:.6f}" if result.get('best_bid') else "Best Bid: N/A")
            st.markdown(f"Best Ask: ${result['best_ask']:.6f}" if result.get('best_ask') else "Best Ask: N/A")
            st.markdown(f"Mid Price: ${result['mid']:.6f}" if result.get('mid') else "Mid Price: N/A")
        
        with col2:
            st.markdown("**Execution Analysis**")
            st.markdown(f"Avg Execution: ${result['avg_exec']:.6f}" if result.get('avg_exec') else "Avg Execution: N/A")
            st.markdown(f"Price Impact: {format_impact_bps(result.get('impact_bps'))} bps")
            
            # Color code based on fillability
            if result.get('filled', False):
                st.markdown("<span style='color: #00ff88'>Order Fillable</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color: #ff6b6b'>Order Not Fillable</span>", unsafe_allow_html=True)
        
        with col3:
            st.markdown("**Order Book Utilization**")
            depth_info = get_depth_summary(result)
            
            st.markdown(f"Levels Touched: {depth_info['levels_touched']}")
            st.markdown(f"Total Levels: {depth_info['total_levels']}")
            st.markdown(f"Utilization: {depth_info['utilization_pct']:.1f}%")
            
            # Progress bar for utilization
            if depth_info['total_levels'] > 0:
                progress = depth_info['levels_touched'] / depth_info['total_levels']
                st.progress(progress)

# Impact visualization
if len(impact_results) > 1:
    st.subheader("Impact Comparison")
    
    # Create chart data
    chart_data = []
    for result in impact_results:
        if result.get('filled', False) and result.get('impact_bps') is not None:
            chart_data.append({
                'Exchange': result['exchange'].upper(),
                'Impact (bps)': result['impact_bps']
            })
    
    if chart_data:
        chart_df = pd.DataFrame(chart_data)
        st.bar_chart(chart_df.set_index('Exchange')['Impact (bps)'], height=300)

# Raw data section
if show_raw and impact_results:
    st.subheader(" Raw Data")
    with st.expander("Show JSON Response"):
        st.json(impact_results)

# Help section
with st.expander("Help & Usage"):
    st.markdown("""
    **Price Impact Analysis:**
    
    **What is Price Impact?**
    - Cost of executing a large order due to moving through order book levels
    - Measured as difference between average execution price and mid price
    - Expressed in basis points (bps): 1 bps = 0.01%
    
    **Key Metrics:**
    - **Average Execution Price:** Weighted average price of filled quantity
    - **Price Impact (bps):** |Avg Exec Price - Mid Price| / Mid Price × 10,000
    - **Levels Touched:** Number of order book levels required
    - **Fillable:** Whether the order can be completely filled
    
    **Interpretation:**
    - **< 5 bps:** Excellent liquidity, minimal impact
    - **5-20 bps:** Good liquidity, acceptable for most trades
    - **20-50 bps:** Moderate impact, consider order splitting
    - **> 50 bps:** High impact, significant cost
    
    **Trading Strategies:**
    - **Single Exchange:** Detailed analysis of specific venue
    - **Multi-Exchange:** Compare execution costs across venues
    - **Best Execution:** Choose venue with lowest impact
    - **Order Splitting:** Break large orders into smaller pieces
    
    **Limitations:**
    - Static snapshot (order book changes in real-time)
    - Doesn't account for market impact on other traders
    - Assumes no slippage during execution
    - Actual execution may differ due to latency
    """)

# Footer
st.markdown("---")
st.caption("Impact analysis based on current order book snapshots.")
st.caption("For CLI analysis: `python TASK1/1.4.py {symbol} --side {side} --volume {notional}`")
