"""
Funding APR Page - Live and historical funding rates with APR calculations

Powered by TASK1/1.3.py
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
    from core.funding import (
        get_multi_funding, funding_history, get_funding_summary, 
        get_supported_exchanges, annualize
    )
    from utils.env import get_secret
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.stop()

# Page configuration
st.set_page_config(
    page_title="Funding APR - Crypto Tools",
    page_icon="�",
    layout="wide"
)# Header
st.title("Funding Rates & APR")
st.markdown("*Live and historical funding rates with yield calculations*")
st.caption("Powered by TASK1/1.3.py")

# Sidebar controls
st.sidebar.header("Controls")

# Symbol input
symbol = st.sidebar.text_input(
    "Trading Pair",
    value="BTCUSDT",
    help="Enter perpetual futures symbol"
).strip().upper()

# Exchange selection
available_exchanges = get_supported_exchanges()
selected_exchanges = st.sidebar.multiselect(
    "Select Exchanges",
    options=available_exchanges,
    default=["binance", "bybit", "deribit"],
    help="Choose exchanges to query funding rates from"
)

# Funding period
period_hours = st.sidebar.selectbox(
    "Funding Period (hours)",
    options=[1, 4, 8, 24],
    index=2,  # Default to 8 hours
    help="Interval between funding payments"
)

# History settings
fetch_history = st.sidebar.checkbox("Fetch Historical Data", value=False)

if fetch_history:
    history_limit = st.sidebar.slider(
        "History Limit",
        min_value=10,
        max_value=500,
        value=100,
        help="Number of historical funding records to fetch"
    )

# Refresh button
if st.sidebar.button(" Refresh Data", type="primary"):
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

# Fetch current funding rates
async def fetch_funding_data():
    """Fetch current funding rates from selected exchanges"""
    try:
        with st.spinner(f"Fetching funding rates for {symbol} from {len(selected_exchanges)} exchanges..."):
            results = await get_multi_funding(selected_exchanges, symbol, period_hours)
            return results
    except Exception as e:
        st.error(f"Error fetching funding data: {str(e)}")
        return []

# Fetch data
try:
    current_rates = asyncio.run(fetch_funding_data())
except Exception as e:
    st.error(f"Failed to fetch funding data: {str(e)}")
    st.stop()

if not current_rates:
    st.warning("No funding data received. Check symbol format and exchange availability.")
    st.stop()

# Display results
st.markdown(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")

# Current rates summary
st.subheader("Current Funding Rates")

if current_rates:
    summary = get_funding_summary(current_rates)
    
    if summary:
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric(
                "Average Rate",
                f"{summary['avg_rate_pct']:.4f}%"
            )
        
        with col2:
            st.metric(
                "Average APR",
                f"{summary['avg_apr']:.2f}%"
            )
        
        with col3:
            st.metric(
                "Min APR",
                f"{summary['min_apr']:.2f}%"
            )
        
        with col4:
            st.metric(
                "Max APR", 
                f"{summary['max_apr']:.2f}%"
            )
        
        with col5:
            st.metric(
                "APR Spread",
                f"{summary['apr_spread']:.2f}%"
            )

# Individual exchange rates
st.subheader(" Exchange Breakdown")

# Create DataFrame for tabular display
df_data = []
for rate_data in current_rates:
    df_data.append({
        "Exchange": rate_data["exchange"].upper(),
        "Symbol": rate_data["symbol"],
        "Funding Rate": f"{rate_data['funding_rate_pct']:.4f}%",
        "Annualized APR": f"{rate_data['apr']:.2f}%",
        "Period (hours)": rate_data["period_hours"]
    })

if df_data:
    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

# Individual exchange cards
st.subheader(" Detailed View")

cols = st.columns(min(len(current_rates), 3))

for i, rate_data in enumerate(current_rates):
    with cols[i % 3]:
        with st.container():
            st.markdown(f"**{rate_data['exchange'].upper()}**")
            st.markdown(f"Symbol: `{rate_data['symbol']}`")
            
            # Funding rate with color coding
            rate_pct = rate_data['funding_rate_pct']
            if rate_pct > 0:
                st.markdown(f"Rate: <span style='color: #ff6b6b'>+{rate_pct:.4f}%</span> (Long pays Short)", unsafe_allow_html=True)
            else:
                st.markdown(f"Rate: <span style='color: #00ff88'>{rate_pct:.4f}%</span> (Short pays Long)", unsafe_allow_html=True)
            
            st.markdown(f"**APR: {rate_data['apr']:.2f}%**")
            st.markdown(f"Period: {rate_data['period_hours']}h")

# Historical data section
if fetch_history:
    st.subheader("Historical Funding Rates")
    
    # Fetch historical data for each exchange
    async def fetch_history_data():
        """Fetch historical funding data"""
        history_data = {}
        
        for exchange in selected_exchanges:
            try:
                with st.spinner(f"Fetching history from {exchange}..."):
                    history = await funding_history(exchange, symbol, history_limit, period_hours)
                    if history:
                        history_data[exchange] = history
            except Exception as e:
                st.warning(f"Could not fetch history from {exchange}: {str(e)}")
        
        return history_data
    
    try:
        history_data = asyncio.run(fetch_history_data())
    except Exception as e:
        st.error(f"Failed to fetch historical data: {str(e)}")
        history_data = {}
    
    if history_data:
        # Create combined chart data
        chart_data = []
        
        for exchange, history in history_data.items():
            for record in history:
                if record.get("timestamp"):
                    try:
                        # Convert timestamp to datetime
                        if isinstance(record["timestamp"], (int, float)):
                            dt = datetime.fromtimestamp(record["timestamp"] / 1000)
                        else:
                            dt = datetime.fromisoformat(str(record["timestamp"]).replace('Z', '+00:00'))
                        
                        chart_data.append({
                            "Timestamp": dt,
                            "APR": record["apr"],
                            "Exchange": exchange.upper(),
                            "Funding Rate %": record["funding_rate_pct"]
                        })
                    except Exception:
                        continue
        
        if chart_data:
            chart_df = pd.DataFrame(chart_data)
            chart_df = chart_df.sort_values("Timestamp")
            
            # Display line chart
            st.subheader("APR Over Time")
            
            # Pivot for line chart
            pivot_df = chart_df.pivot(index="Timestamp", columns="Exchange", values="APR")
            st.line_chart(pivot_df, height=400)
            
            # Statistics table
            st.subheader("📋 Historical Statistics")
            
            stats_data = []
            for exchange, history in history_data.items():
                aprs = [record["apr"] for record in history if record.get("apr") is not None]
                
                if aprs:
                    stats_data.append({
                        "Exchange": exchange.upper(),
                        "Records": len(aprs),
                        "Avg APR": f"{sum(aprs) / len(aprs):.2f}%",
                        "Min APR": f"{min(aprs):.2f}%",
                        "Max APR": f"{max(aprs):.2f}%",
                        "Volatility": f"{(max(aprs) - min(aprs)):.2f}%"
                    })
            
            if stats_data:
                stats_df = pd.DataFrame(stats_data)
                st.dataframe(stats_df, use_container_width=True, hide_index=True)

# APR Calculator
st.subheader(" APR Calculator")

with st.expander("Calculate APR from Funding Rate"):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        calc_rate = st.number_input(
            "Funding Rate (%)",
            value=0.01,
            step=0.001,
            format="%.4f",
            help="Enter funding rate as percentage"
        )
    
    with col2:
        calc_period = st.selectbox(
            "Period (hours)",
            options=[1, 4, 8, 24],
            index=2
        )
    
    with col3:
        st.markdown("**Calculated APR:**")
        calc_apr = annualize(calc_rate / 100, calc_period)
        st.markdown(f"**{calc_apr:.2f}%**")
        
        st.caption(f"Rate: {calc_rate}% every {calc_period}h")
        st.caption(f"Periods per year: {365 * 24 / calc_period:.1f}")

# Raw data section
if show_raw and current_rates:
    st.subheader(" Raw Data")
    with st.expander("Show JSON Response"):
        st.json(current_rates)

# Help section
with st.expander("Help & Usage"):
    st.markdown("""
    **Funding Rates Explained:**
    
    **What are Funding Rates?**
    - Periodic payments between long and short positions
    - Designed to keep perpetual futures prices close to spot
    - Positive rate: Longs pay shorts
    - Negative rate: Shorts pay longs
    
    **APR Calculation:**
    - APR = Funding Rate × (365 × 24 / Period Hours) × 100
    - Annualizes the periodic rate for comparison
    - Shows potential yearly yield from funding payments
    
    **Exchange Differences:**
    - **Binance:** 8-hour funding (3 times daily)
    - **Bybit:** 8-hour funding (3 times daily)  
    - **Deribit:** 8-hour funding (3 times daily)
    - Different exchanges may have slightly different rates
    
    **Trading Implications:**
    - High positive rates: Consider shorting
    - High negative rates: Consider longing
    - Rate spreads indicate arbitrage opportunities
    - Historical volatility shows rate stability
    
    **Limitations:**
    - Rates change every funding period
    - Past performance doesn't guarantee future results
    - Market conditions affect funding sustainability
    """)

# Footer
st.markdown("---")
st.caption("Funding rates sourced from exchange APIs. Rates update every funding period.")
st.caption("For live monitoring, use: `python TASK1/1.3.py {symbol} --exch all`")
