# Streamlit Crypto Trading Tools

A professional web interface for cryptocurrency market data analysis and testnet trading, built on top of production-ready CLI tools.

## Quick Start

### Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Run the webapp
streamlit run webapp/app.py
```

### Secrets Configuration

Choose one of these methods to configure API keys:

**Option 1: Environment Variables (.env file)**
```bash
# Copy example and edit
cp env_example.txt .env
# Edit .env with your API keys
```

**Option 2: Streamlit Secrets**
```bash
# Copy example and edit
cp webapp/.streamlit/secrets.example.toml webapp/.streamlit/secrets.toml
# Edit secrets.toml with your API keys
```

## Application Pages

### Live Ticker
- **Purpose:** Real-time price comparison across 6+ exchanges
- **Features:** 
  - Auto-refresh capabilities
  - Cross-exchange spread analysis
  - Multiple symbol format support
  - Best bid/ask aggregation
- **Data Sources:** Binance, BitMart, Deribit, KuCoin, OKX, Hyperliquid
- **CLI Equivalent:** `python TASK1/1.1.py BTCUSDT --exch all`

### 📚 Order Book Analyzer
- **Purpose:** L2 order book depth analysis and market structure
- **Features:**
  - Full market depth visualization
  - Cumulative volume analysis
  - Top-N level breakdown
  - Real-time market metrics
- **Data Sources:** All major exchanges with L2 support
- **CLI Equivalent:** `python TASK1/1.2.py BTCUSDT --exch binance --limit 200`

### 💰 Funding Rates & APR
- **Purpose:** Funding rate analysis with yield calculations
- **Features:**
  - Multi-exchange rate comparison
  - Historical funding data
  - APR calculations and projections
  - Rate change visualization
- **Data Sources:** Binance, Bybit, Deribit, KuCoin, Hyperliquid
- **CLI Equivalent:** `python TASK1/1.3.py BTCUSDT --exch all --history`

### 📊 Price Impact Analyzer
- **Purpose:** Order book walking and execution cost simulation
- **Features:**
  - Multi-exchange impact comparison
  - Order book depth utilization
  - Best execution venue analysis
  - Impact visualization
- **Data Sources:** Binance, Bybit, KuCoin, Deribit, Hyperliquid
- **CLI Equivalent:** `python TASK1/1.4.py BTCUSDT --side buy --volume 10000 --exch all`

### ⚡ Trading Console (TESTNET ONLY)
- **Purpose:** Safe order management using testnet environments
- **Features:**
  - LIMIT and MARKET order placement
  - Order cancellation and status tracking
  - Real-time latency monitoring
  - Recent orders management
- **Safety:** **TESTNET ONLY** - uses fake money, no real trading
- **Supported:** Binance Testnet, Bybit Testnet, Deribit Testnet
- **CLI Equivalent:** `python TASK2.3.4/2.1.py --exch binance --testnet place BTCUSDT --side BUY --type MARKET --quote 10`

## 🔧 Architecture

### Core Modules (`webapp/core/`)
- **ticker.py** - Extracted from TASK1/1.1.py for price data
- **orderbook.py** - Extracted from TASK1/1.2.py for L2 data
- **funding.py** - Extracted from TASK1/1.3.py for funding rates
- **impact.py** - Extracted from TASK1/1.4.py for price impact
- **trade.py** - Extracted from TASK2.3.4/2.1.py for trading (testnet only)

### Utilities (`webapp/utils/`)
- **env.py** - Environment and secrets management

### Original CLI Tools (Preserved)
- All original scripts under `TASK1/` and `TASK2.3.4/` remain fully functional
- No breaking changes to existing CLI interfaces
- Webapp uses extracted core functions, not CLI wrappers

## 🛡️ Security & Safety

### Trading Safety
- **Webapp trading is TESTNET ONLY** - no real money can be lost
- Production trading requires CLI tools with live API keys
- Clear visual warnings throughout trading interface
- API credentials loaded from secure environment variables

### API Key Management
- Secrets loaded from `.env` or Streamlit `secrets.toml`
- No hardcoded credentials in source code
- Graceful fallback when credentials missing
- Support for both environment variables and Streamlit secrets

### Error Handling
- Comprehensive exception handling in all core modules
- User-friendly error messages in Streamlit interface
- Graceful degradation when exchanges are unavailable
- Input validation and sanitization

## 📊 Features & Capabilities

### Real-time Data
- Live price feeds from multiple exchanges
- WebSocket streaming capabilities (CLI tools)
- Auto-refresh functionality in webapp
- Configurable update intervals

### Multi-Exchange Support
- **Market Data:** 6+ exchanges (Binance, BitMart, Deribit, KuCoin, OKX, Hyperliquid)
- **Trading:** 3 testnet exchanges (Binance, Bybit, Deribit)
- **Symbol Normalization:** Automatic format detection and conversion
- **Cross-Exchange Analysis:** Spread analysis and arbitrage detection

### Professional Analysis
- **Order Book Walking:** Production-grade price impact calculation
- **Funding Analysis:** Historical and predictive yield calculations
- **Market Structure:** Deep liquidity and depth analysis
- **Performance Metrics:** Latency tracking and execution analytics

## 🔍 Troubleshooting

### Common Issues

**"Failed to import core modules"**
- Ensure all dependencies installed: `pip install -r requirements.txt`
- Check Python path and module imports
- Verify TASK1/ and TASK2.3.4/ directories exist

**"No API credentials found"**
- Configure `.env` file or `.streamlit/secrets.toml`
- Check environment variable names match expected format
- Verify API keys are valid for testnet environments

**"No data received"**
- Check symbol format (BTCUSDT, BTC-USDT, etc.)
- Verify exchange availability and API limits
- Try different exchanges or reduce request frequency

**High latency or timeouts**
- Check internet connection
- Reduce number of simultaneous exchange requests
- Use CLI tools for high-frequency applications

### Performance Optimization

**For High-Frequency Data:**
- Use CLI tools directly instead of webapp
- Enable WebSocket streaming: `python TASK1/1.1.py BTCUSDT --ws`
- Reduce Streamlit auto-refresh intervals

**For Large Orders:**
- Use price impact analyzer before trading
- Consider order splitting for large sizes
- Test on multiple exchanges for best execution

## 📚 API Documentation

### Core Module APIs

Each core module provides standardized async functions:

```python
# Ticker data
from core.ticker import get_multi_best_bid_ask
results = await get_multi_best_bid_ask(["binance", "kucoin"], "BTCUSDT")

# Order book data  
from core.orderbook import get_l2_orderbook
book = await get_l2_orderbook("binance", "BTCUSDT", limit=200)

# Funding rates
from core.funding import current_funding
rate = await current_funding("binance", "BTCUSDT", period_hours=8)

# Price impact
from core.impact import estimate_price_impact  
impact = await estimate_price_impact("binance", "BTCUSDT", "buy", 10000)

# Trading (testnet only)
from core.trade import place_order_testnet
result = place_order_testnet("binance", "BTCUSDT", "BUY", "MARKET", quote=10)
```

### CLI Integration

All webapp functionality maps directly to CLI commands:

```bash
# Live ticker
python TASK1/1.1.py BTCUSDT --exch all

# Order book
python TASK1/1.2.py BTCUSDT --exch binance --limit 200

# Funding rates
python TASK1/1.3.py BTCUSDT --exch all --history

# Price impact
python TASK1/1.4.py BTCUSDT --side buy --volume 10000 --exch all

# Trading (testnet)
python TASK2.3.4/2.1.py --exch binance --testnet place BTCUSDT --side BUY --type MARKET --quote 10
```

## 🎯 Development

### Adding New Features
1. Extract reusable functions to `webapp/core/` modules
2. Keep original CLI tools unchanged
3. Add new Streamlit pages under `webapp/pages/`
4. Update navigation in `webapp/app.py`
5. Add comprehensive error handling

### Testing
```bash
# Test CLI tools (ensure no breaking changes)
python TASK1/1.1.py BTCUSDT --exch binance
python TASK2.3.4/2.1.py --exch binance --testnet debug-mark BTCUSDT

# Test webapp
streamlit run webapp/app.py
```

### Code Style
- Type hints for all function signatures
- Comprehensive docstrings
- Async/await for network operations
- Graceful error handling with user feedback

## 📄 License & Credits

Built on top of the existing CLI cryptocurrency trading tools. The webapp layer adds a user-friendly interface while preserving all original functionality and maintaining production-grade reliability.

**Core Technologies:**
- **Streamlit** - Web interface framework
- **AsyncIO** - Asynchronous network operations  
- **Pandas** - Data manipulation and analysis
- **HTTPX/AioHTTP** - HTTP client libraries
- **Python-dotenv** - Environment variable management

**Original CLI Tools:**
- TASK1/ - Market data analysis tools
- TASK2.3.4/ - Trading execution engine
- TASK5.py - Data pipeline (not integrated in webapp)

**Production Ready:**
- Type-safe Python codebase
- Comprehensive error handling
- Security-first design
- Modular architecture
- CLI tool compatibility maintained
