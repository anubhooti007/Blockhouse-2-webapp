"""
Crypto Trading Tools - Streamlit Web Application

Multi-page web interface for cryptocurrency market data and trading tools.
Built on top of the existing CLI scripts in TASK1/ and TASK2.3.4/.
"""
import streamlit as st
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Crypto Trading Tools",
    page_icon="🔷",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Add custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #00f5ff;
        text-align: center;
        margin-bottom: 2rem;
    }
    .feature-box {
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #00f5ff;
        background-color: #262730;
        margin: 1rem 0;
    }
    .warning-box {
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #ff6b6b;
        background-color: #2d1b1b;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Main header
st.markdown('<h1 class="main-header">Crypto Trading Tools</h1>', unsafe_allow_html=True)

# Introduction
st.markdown("""
Welcome to the **Crypto Trading Tools** web interface! This application provides a user-friendly 
way to access advanced cryptocurrency market data and trading functionality.

Built on top of production-ready CLI tools, this webapp offers:
""")

# Feature overview
col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class="feature-box">
        <h3>Market Data Tools</h3>
        <ul>
            <li><strong>Live Ticker:</strong> Real-time bid/ask prices across 6+ exchanges</li>
            <li><strong>Order Books:</strong> Full L2 depth analysis with WebSocket streaming</li>
            <li><strong>Funding Rates:</strong> Live and historical funding with APR calculations</li>
            <li><strong>Price Impact:</strong> Order book walking and execution simulation</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="feature-box">
        <h3>Trading Console</h3>
        <ul>
            <li><strong>TESTNET Only:</strong> Safe trading environment for learning</li>
            <li><strong>Multi-Exchange:</strong> Binance, Bybit, Deribit testnet support</li>
            <li><strong>Order Management:</strong> Place, cancel, and monitor orders</li>
            <li><strong>Real-time Monitoring:</strong> Live position and PnL tracking</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

# Safety warning
st.markdown("""
<div class="warning-box">
    <h3>IMPORTANT - Trading Safety</h3>
    <p>This webapp is configured for <strong>TESTNET TRADING ONLY</strong> for safety. 
    All trading functions use fake money on exchange test environments.</p>
    <ul>
        <li><strong>Testnet Supported:</strong> Binance, Bybit, Deribit (free fake money)</li>
        <li><strong>No Real Money:</strong> Cannot place live trades through this interface</li>
        <li><strong>Learning Safe:</strong> Perfect for testing strategies and learning</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Navigation
st.sidebar.title("Navigation")
st.sidebar.markdown("Select a page to explore:")

# Page links
pages = [
    ("01_Live_Ticker", "Live Ticker", "Real-time price comparison across exchanges"),
    ("02_Order_Book", "Order Book", "L2 depth analysis and market structure"),
    ("03_Funding_APR", "Funding & APR", "Funding rates and yield calculations"),
    ("04_Price_Impact", "Price Impact", "Order book walking and execution costs"),
    ("05_Trade_Console_TESTNET", "Trading Console", "TESTNET order management (safe)")
]

for page_file, display_name, description in pages:
    st.sidebar.page_link(f"pages/{page_file}.py", label=display_name, help=description)

# Sidebar info
st.sidebar.markdown("---")
st.sidebar.markdown("""
### Setup Required
1. Install dependencies: `pip install -r requirements.txt`
2. Configure API keys in `.env` or `.streamlit/secrets.toml`
3. Create testnet accounts for safe trading

### 📁 Powered By
- **TASK1/** - Market data CLI tools
- **TASK2.3.4/** - Trading engine CLI
- **TASK5.py** - Data pipeline (not in webapp)
""")

# About section
st.markdown("---")
st.subheader("About This Application")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    **Architecture**
    - Streamlit frontend
    - Modular core functions
    - Original CLI tools preserved
    - Type-safe Python codebase
    """)

with col2:
    st.markdown("""
    **Data Sources**
    - Binance, BitMart, Deribit
    - KuCoin, OKX, Hyperliquid
    - Real-time WebSocket streams
    - REST API snapshots
    """)

with col3:
    st.markdown("""
    **Security**
    - Testnet-only trading
    - Environment variable secrets
    - No hardcoded credentials
    - Graceful error handling
    """)

# Documentation download
project_root = Path(__file__).parent.parent
doc_path = project_root / "Work_trail_Crypto (2).pdf"

if doc_path.exists():
    st.markdown("---")
    st.subheader("Documentation")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        with open(doc_path, "rb") as file:
            st.download_button(
                label="📥 Download Full Documentation",
                data=file.read(),
                file_name="Crypto_Trading_Tools_Documentation.pdf",
                mime="application/pdf"
            )
    
    with col2:
        st.info("Download the complete documentation for detailed setup instructions and advanced usage.")

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; margin-top: 2rem;">
    <p>Built with Streamlit | Powered by Python | Production-Ready CLI Tools</p>
    <p>Start with the <strong>Live Ticker</strong> page to explore real-time market data!</p>
</div>
""", unsafe_allow_html=True)
