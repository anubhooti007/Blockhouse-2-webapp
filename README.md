# Cryptocurrency Trading Tools

## Overview
**TASK 1:** Four complementary tools for cryptocurrency market data  
**TASK 2,3,4:** Robust trade execution and order management system  
**TASK 5:** Historical L2 order book data persistence for backtesting

### 1.1.py - Best Bid/Ask Aggregator
Fetches and aggregates best bid/ask prices from 6 exchanges (BitMart, Binance, Deribit, KuCoin, OKX, Hyperliquid) with REST snapshots and WebSocket streaming.

### 1.2.py - L2 Order Book Analyzer  
Comprehensive L2 order book data retrieval and analysis across 7 exchanges with real-time WebSocket streaming and JSON export.

### 1.3.py - Funding Rates Monitor
Fetches live/current and predicted funding rates across 5 exchanges with historical data analysis and APR calculations.

### 1.4.py - Order Book Depth & Price Impact
Production-ready order book depth and price impact analyzer. Calculates effective execution price and price impact by walking order books across 5 exchanges. Implements the exact formula: |AverageExecutionPrice - MarketMidPrice| / MarketMidPrice × 100%.

### 2.1.py - Trade Execution & Order Management
Unified trading system for placing, cancelling, and tracking orders across multiple exchanges. Supports both LIMIT and MARKET orders with comprehensive performance testing and real-time position monitoring.

### TASK5.py - L2 Order Book Data Pipeline
Production-ready data pipeline that captures and stores full-depth L2 order book snapshots with venue timestamps for backtesting. Features dual storage backends (local Parquet + optional S3), real-time monitoring, and comprehensive data loss detection.

## Installation

**Requirements:** Python 3.7+ (3.9+ recommended)

### Quick Install (All Features)
```bash
pip install -r requirements.txt
```

### Minimal Install (TASK1 Only)
```bash
pip install aiohttp>=3.8.0
```

### Trading Features (TASK2.3.4)
```bash
pip install requests>=2.28.0 python-dotenv>=0.19.0
```

### Data Pipeline (TASK5)
```bash
pip install aiohttp>=3.8.0 pandas>=1.5.0 pyarrow>=10.0.0 boto3>=1.26.0 websockets>=10.0 numpy>=1.21.0 pytz>=2022.1
```

## Environment Setup

### Quick Setup (Recommended)
```bash
# Copy the example environment file
cp env_example.txt .env

# Edit with your API keys
# Windows: notepad .env
# macOS/Linux: nano .env
```

### Manual Setup
Create a `.env` file in the project root with your API keys (see `env_example.txt` for template).

**IMPORTANT - TESTNET**
- **Always start with TESTNET** for learning and testing (use `--testnet` flag)
- Testnet is available for: Binance, Bybit, Deribit (free fake money for testing)
- Live trading requires actual API keys and uses real money
- Set up testnet accounts first at the URLs provided in environment variables section or use the ones in `env_example.txt` file (copy to `.env`)

**TESTNET Setup (Recommended for Learning):**
```bash
# Binance Testnet (https://testnet.binance.vision/)
BINANCE_API_KEY=your_testnet_api_key
BINANCE_API_SECRET=your_testnet_api_secret

# Bybit Testnet (https://testnet.bybit.com/)
BYBIT_API_KEY=your_testnet_api_key
BYBIT_API_SECRET=your_testnet_api_secret

# Deribit Testnet (https://test.deribit.com/)
DERIBIT_CLIENT_ID=your_testnet_client_id
DERIBIT_CLIENT_SECRET=your_testnet_client_secret
```

**Quick Start:** Copy `env_example.txt` to `.env` and replace the placeholder values with your actual testnet API keys or use the ones mentioned in the env_example.txt.

**LIVE TRADING Setup (Use Real Money):**
```bash
# KuCoin (Live Only - https://www.kucoin.com/)
KUCOIN_API_KEY=your_live_api_key
KUCOIN_API_SECRET=your_live_api_secret
KUCOIN_PASSPHRASE=your_live_passphrase

# BitMart (Live Only - https://www.bitmart.com/)
BITMART_API_KEY=your_live_api_key
BITMART_API_SECRET=your_live_api_secret
BITMART_MEMO=your_live_memo

# OKX (Live Only - https://www.okx.com/ - Geo-restricted in India)
OKX_API_KEY=your_live_api_key
OKX_API_SECRET=your_live_api_secret
OKX_PASSPHRASE=your_live_passphrase

# Optional: For live trading on testnet-supported exchanges
# BINANCE_API_KEY=your_live_api_key      # Remove --testnet flag
# BINANCE_API_SECRET=your_live_api_secret
# BYBIT_API_KEY=your_live_api_key        # Remove --testnet flag
# BYBIT_API_SECRET=your_live_api_secret
# DERIBIT_CLIENT_ID=your_live_client_id  # Remove --testnet flag
# DERIBIT_CLIENT_SECRET=your_live_client_secret
``` 

## Usage

### 1.1.py - Best Bid/Ask Aggregator
```bash
python TASK1/1.1.py <TOKEN> [--ws] [--exch <EXCHANGE>]
```
**Exchanges:** `binance`, `bitmart`, `deribit`, `kucoin`, `okx`, `hyperliquid`, `all`

**Examples:**
```bash
python TASK1/1.1.py BTCUSDT --exch all                    # All exchanges comparison
python TASK1/1.1.py ETHUSDT --exch binance               # Single exchange
python TASK1/1.1.py BTCUSDT --ws --exch all              # Real-time streaming
python TASK1/1.1.py BTCUSDT --exch deribit               # Perpetual futures
python TASK1/1.1.py BTC --exch hyperliquid               # Different symbol format
```

### 1.2.py - L2 Order Book Analyzer
```bash
python TASK1/1.2.py <PAIR> [--exch <EXCHANGE>] [--ws] [--limit <DEPTH>] [--out <FILE>]
```
**Exchanges:** `binance`, `kucoin`, `bybit`, `deribit`, `bitmart`, `okx`, `hyperliquid`, `all`

**Examples:**
```bash
python TASK1/1.2.py BTCUSDT --exch all --out orderbook.json    # Export to JSON
python TASK1/1.2.py ETHUSDT --exch binance --limit 50          # Custom depth
python TASK1/1.2.py BTCUSDT --ws --exch kucoin                 # Live streaming
python TASK1/1.2.py BTC-PERPETUAL --exch deribit               # Perpetual futures
python TASK1/1.2.py ETHUSDT --exch bybit --category linear     # Bybit categories
```

### 1.3.py - Funding Rates Monitor
```bash
python TASK1/1.3.py <SYMBOL> [--exch <EXCHANGE>] [--history] [--limit <COUNT>]
```
**Exchanges:** `binance`, `bybit`, `deribit`, `kucoin`, `hyperliquid`, `all`

**Examples:**
```bash
python TASK1/1.3.py BTCUSDT --exch all --history              # Historical rates
python TASK1/1.3.py ETHUSDT --exch deribit --period-hours 8   # Custom period
python TASK1/1.3.py BTCUSDT --exch binance --limit 10         # Last 10 rates
python TASK1/1.3.py ETHUSDT --exch hyperliquid                # Single exchange
python TASK1/1.3.py BTCUSDT --exch all                        # Live rates comparison
```

### 1.4.py - Order Book Depth & Price Impact
```bash
python TASK1/1.4.py <PAIR> --side <SIDE> --volume <VOLUME> [--exch <EXCHANGE>] [--json <FILE>] [--dp-pct <DECIMALS>] [--dp-bps <DECIMALS>]
```
**Exchanges:** `binance`, `bybit`, `kucoin`, `deribit`, `hyperliquid`, `all`

**Examples:**
```bash
python TASK1/1.4.py BTCUSDT --side buy --volume 50000 --exch all --json results.json    # Export analysis
python TASK1/1.4.py ETHUSDT --side sell --volume 100000 --exch binance --dp-pct 6        # Custom precision
python TASK1/1.4.py BTCUSDT --side buy --volume 1000 --exch bybit --category linear      # Bybit futures
python TASK1/1.4.py BTCUSDT --side buy --volume 50000 --exch deribit --deribit-contract-usd 100.0  # Custom contract
python TASK1/1.4.py ETHUSDT --side sell --volume 25000 --exch all                        # Multi-exchange comparison
```

---

## TASK 2.3.4 - Trade Execution & Order Management

### 2.1.py - Trade Execution & Order Management
```bash
python TASK2.3.4/2.1.py --exch <EXCHANGE> <COMMAND> <SYMBOL> [OPTIONS]
```
**Exchanges:** `binance`, `bybit`, `deribit`, `kucoin`, `bitmart`, `okx`

**Trading Safety Notes:** 
- **TESTNET (Safe):** Binance, Bybit, Deribit - Use `--testnet` flag for practice
- **LIVE ONLY:** KuCoin, BitMart, OKX - No testnet, real money only
- **GEO-BLOCK:** OKX not accessible from India
- **API Setup:** Create testnet accounts first, then optionally add live keys

**Commands:**

#### TESTNET Examples (Safe Testing)
**Binance Testnet:**
```bash
python TASK2.3.4/2.1.py --exch binance --testnet place BTCUSDT --side BUY --type LIMIT --qty 0.001 --price 50000
python TASK2.3.4/2.1.py --exch binance --testnet place BTCUSDT --side SELL --type MARKET --quote 10
python TASK2.3.4/2.1.py --exch binance --testnet place ETHUSDT --side BUY --type LIMIT --qty 0.01 --price 3000
python TASK2.3.4/2.1.py --exch binance --testnet cancel BTCUSDT --order-id 12345
python TASK2.3.4/2.1.py --exch binance --testnet status BTCUSDT --order-id 12345
python TASK2.3.4/2.1.py --exch binance --testnet perftest BTCUSDT --count 50 --duration 120
python TASK2.3.4/2.1.py --exch binance --testnet monitor BTCUSDT --order-id 12345
```

**Bybit Testnet:**
```bash
python TASK2.3.4/2.1.py --exch bybit --testnet place BTCUSDT --side BUY --type LIMIT --qty 0.001 --price 50000
python TASK2.3.4/2.1.py --exch bybit --testnet place ETHUSDT --side SELL --type MARKET --qty 0.01
python TASK2.3.4/2.1.py --exch bybit --testnet place SOLUSDT --side BUY --type LIMIT --qty 1 --price 100
python TASK2.3.4/2.1.py --exch bybit --testnet cancel BTCUSDT --order-id 67890
python TASK2.3.4/2.1.py --exch bybit --testnet status ETHUSDT --client-id MY_ORDER_123
python TASK2.3.4/2.1.py --exch bybit --testnet perftest BTCUSDT --count 30 --duration 60
python TASK2.3.4/2.1.py --exch bybit --testnet monitor BTCUSDT --order-id 67890
```

**Deribit Testnet:**
```bash
python TASK2.3.4/2.1.py --exch deribit --testnet place BTCUSDT --side BUY --type LIMIT --qty 10 --price 50000
python TASK2.3.4/2.1.py --exch deribit --testnet place ETHUSDT --side SELL --type MARKET --qty 1
python TASK2.3.4/2.1.py --exch deribit --testnet place BTCUSDT --side BUY --type LIMIT --qty 5 --price 45000 --reduce-only
python TASK2.3.4/2.1.py --exch deribit --testnet cancel BTCUSDT --order-id 54321
python TASK2.3.4/2.1.py --exch deribit --testnet status BTCUSDT --order-id 54321
python TASK2.3.4/2.1.py --exch deribit --testnet perftest BTCUSDT --count 100 --duration 180
python TASK2.3.4/2.1.py --exch deribit --testnet monitor BTCUSDT --order-id 54321
```

#### LIVE TRADING Examples (Actual API Keys Required)
**KuCoin (Live Only):**
```bash
python TASK2.3.4/2.1.py --exch kucoin place BTC-USDT --side BUY --type LIMIT --qty 0.001 --price 50000
python TASK2.3.4/2.1.py --exch kucoin place ETH-USDT --side SELL --type MARKET --qty 0.01
python TASK2.3.4/2.1.py --exch kucoin cancel BTC-USDT --order-id 11111
python TASK2.3.4/2.1.py --exch kucoin status BTC-USDT --order-id 11111
python TASK2.3.4/2.1.py --exch kucoin perftest BTCUSDT --count 20 --duration 120
python TASK2.3.4/2.1.py --exch kucoin monitor BTCUSDT --order-id 11111
```

**BitMart (Live Only):**
```bash
python TASK2.3.4/2.1.py --exch bitmart place BTC_USDT --side BUY --type LIMIT --qty 0.001 --price 50000
python TASK2.3.4/2.1.py --exch bitmart place ETH_USDT --side SELL --type MARKET --qty 0.01
python TASK2.3.4/2.1.py --exch bitmart cancel BTC_USDT --order-id 22222
python TASK2.3.4/2.1.py --exch bitmart status BTC_USDT --order-id 22222
python TASK2.3.4/2.1.py --exch bitmart perftest BTC_USDT --count 15 --duration 90
python TASK2.3.4/2.1.py --exch bitmart monitor BTC_USDT --order-id 22222
```

**OKX (Live Only - Geo-restricted in India):**
```bash
python TASK2.3.4/2.1.py --exch okx place BTC-USDT --side BUY --type LIMIT --qty 0.001 --price 50000
python TASK2.3.4/2.1.py --exch okx place ETH-USDT --side SELL --type MARKET --qty 0.01
python TASK2.3.4/2.1.py --exch okx cancel BTC-USDT --order-id 33333
python TASK2.3.4/2.1.py --exch okx status BTC-USDT --order-id 33333
python TASK2.3.4/2.1.py --exch okx perftest BTCUSDT --count 25 --duration 100
python TASK2.3.4/2.1.py --exch okx monitor BTCUSDT --order-id 33333
```

#### Additional Utility Commands
**Symbol Testing:**
```bash
python TASK2.3.4/2.1.py symbol-test BTCUSDT           # Test symbol mapping for BTCUSDT
python TASK2.3.4/2.1.py symbol-test BTC-USDT          # Test hyphen format
python TASK2.3.4/2.1.py symbol-test "BTC/USDT"        # Test slash format
python TASK2.3.4/2.1.py symbol-test 1000BONK-USD      # Test multiplier format
```

**Debug Mark Prices:**
```bash
python TASK2.3.4/2.1.py --exch binance --testnet debug-mark BTCUSDT      # Test live price updates
python TASK2.3.4/2.1.py --exch bybit --testnet debug-mark ETHUSDT        # Bybit price monitoring
python TASK2.3.4/2.1.py --exch deribit --testnet debug-mark BTCUSDT      # Deribit mark prices
```

---

## TASK 5 - L2 Order Book Data Pipeline

### TASK5.py - Historical Data Persistence for Backtesting
```bash
python TASK5.py [--binance-ws] [--exch <EXCHANGE>] [--pair <SYMBOL>] [OPTIONS]
```

**Core Features:**
- Full-depth L2 order book capture with venue timestamps
- Dual storage: Local Parquet files + optional S3 upload
- Configurable capture frequency (1 second default)
- Real-time WebSocket streaming (Binance) and REST polling
- Non-blocking S3 uploads with automatic retry
- Comprehensive data loss detection and health metrics

### AWS S3 Setup (Optional)

**1. Install AWS CLI:**
```bash
# Windows
winget install Amazon.AWSCLI
# or download from: https://aws.amazon.com/cli/

# macOS
brew install awscli

# Linux
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

**2. Configure AWS Credentials:**
```bash
aws configure
# AWS Access Key ID: [your_access_key]
# AWS Secret Access Key: [your_secret_key]
# Default region name: [us-east-1]
# Default output format: [json]
```

**3. Create S3 Bucket:**
```bash
aws s3 mb s3://my-crypto-data-2025 --region us-east-1
```

**4. Verify Configuration:**
```bash
aws configure list
aws s3 ls s3://my-crypto-data-2025
```

### Usage Examples

#### Local Storage Only (No AWS Required)
```bash
# Binance WebSocket mode (recommended for continuous capture)
python TASK5.py --binance-ws

# Main engine with local storage
python TASK5.py --exch binance --pair BTCUSDT --interval 1

# Multi-exchange capture
python TASK5.py --exch all --pair BTCUSDT --depth max --interval 2
```

#### Local + S3 Storage (AWS Required)
```bash
# Set environment variables
export S3_BUCKET=my-crypto-data-2025
export S3_REGION=us-east-1

# WebSocket mode with S3 upload
python TASK5.py --binance-ws

# Main engine with S3
python TASK5.py --exch binance --pair BTCUSDT --s3-bucket my-crypto-data-2025

# Long-running capture with S3 backup
python TASK5.py --exch all --pair BTCUSDT --depth max --s3-bucket my-crypto-data-2025 --minutes 60
```

#### Advanced Options
```bash
# Custom capture parameters
python TASK5.py --exch binance --pair BTCUSDT --depth 1000 --interval 0.5

# Specific exchange with custom depth
python TASK5.py --exch bybit --pair ETHUSDT --depth 500 --interval 1

# Production capture with environment variables
export PAIR=BTCUSDT
export S3_BUCKET=prod-orderbooks
python TASK5.py --binance-ws
```

### Data Storage Structure

**Local Files:**
```
data/
├── binance/
│   └── BTCUSDT/
│       └── 2025-01-27/
│           └── 14/
│               └── snapshot_1706364000000.parquet
```

**S3 Structure:**
```
s3://my-crypto-data-2025/
└── orderbooks/
    └── exchange=binance/
        └── pair=BTCUSDT/
            └── date=2025-01-27/
                └── hour=14/
                    └── part-14-1706364000000.parquet
```

### Schema
Each Parquet file contains:
- `ts_venue_ns`: High-precision venue timestamp (nanoseconds)
- `ts_capture_ns`: Local capture timestamp (nanoseconds)
- `ts_source`: Timestamp source ("venue" or "local_fallback")
- `exchange`: Exchange name
- `pair`: Trading pair
- `bids`: Full bid array `[[price, quantity], ...]`
- `asks`: Full ask array `[[price, quantity], ...]`
- `bid_count`: Number of bid levels
- `ask_count`: Number of ask levels

### Monitoring & Health
- **Automatic Logging:** Progress updates every 30 seconds
- **S3 Upload Status:** Success/failure tracking with retry logic
- **Data Loss Detection:** Comprehensive error logging and recovery
- **Performance Metrics:** Capture rate, upload queue depth, file counts

---

## Key Features

### 1.1.py
- Real-time price comparison across exchanges
- WebSocket streaming and REST snapshots
- Automatic symbol normalization
- Geo-blocking detection and fallback

### 1.2.py
- Full L2 order books with customizable depth
- Real-time WebSocket streaming
- JSON export for analysis
- Market depth analysis (spread, mid-price)

### 1.3.py
- Live and predicted funding rates
- Historical funding rate analysis
- APR calculations with custom periods
- Multi-timeframe support (1h, 4h, 8h)

### 1.4.py
- Order book walking simulation
- Price impact calculation with exact formula
- Multi-exchange batch processing
- JSON export with comprehensive metrics
- Exchange-specific parameters (Bybit categories, Deribit contracts)
- Configurable precision and error handling

### 2.1.py
- Unified order placement (LIMIT & MARKET orders)
- Multi-exchange support (Binance, Bybit, Deribit, KuCoin, BitMart, OKX)
- Order cancellation and status tracking
- Performance testing with latency metrics
- Real-time position and PnL monitoring
- Testnet support for safe testing (Binance, Bybit, Deribit)
- Live trading with actual API keys (KuCoin, BitMart, OKX)
- Universal symbol mapping and time synchronization
- Geo-restriction awareness (OKX blocked in India)

### TASK5.py
- Full-depth L2 order book capture with venue timestamps
- Dual storage: Local Parquet files + optional S3 upload
- Real-time WebSocket streaming (Binance) and REST polling
- Non-blocking S3 uploads with automatic retry and validation
- Configurable capture frequency and depth (including full market depth)
- Data partitioning by exchange/pair/date/hour for optimal querying
- Comprehensive health metrics and error logging
- Automatic directory creation and file management
- Environment variable configuration for S3 integration

---

## Open-Ended Challenge: Architectural Review & Strategy Proposal

The current system architecture, while functional for prototyping and small-scale operations, exhibits several critical weaknesses that would prevent it from scaling to production-grade trading operations:

**Primary Weaknesses:**

1. **API Rate Limiting Bottlenecks:**
   - **Current Issue:** All exchange APIs have strict rate limits (Binance: 1200 requests/minute, Bybit: 100 requests/second, etc.)
   - **Bottleneck:** Synchronous REST API calls create artificial delays and potential rate limit violations
   - **Impact:** High-frequency data capture (Task 5) and real-time trading (Task 2.3.4) become unreliable under load

2. **Single Points of Failure:**
   - **Network Connectivity:** Single HTTP session per exchange with no failover mechanisms
   - **Exchange Downtime:** No redundancy when exchanges experience outages (common in crypto markets)
   - **Data Storage:** Single S3 bucket or database instance creates critical dependency
   - **Process Architecture:** Monolithic single-process design with no health monitoring or auto-restart

3. **Latency and Performance Issues:**
   - **Sequential Processing:** Order book walking (Task 1.4) processes exchanges sequentially rather than in parallel
   - **Memory Inefficiency:** Full order book snapshots stored in memory without streaming or compression
   - **Blocking Operations:** Database writes and S3 uploads block the main capture loop
   - **No Caching:** Repeated API calls for static data (symbol mappings, exchange info)

4. **Scalability Limitations:**
   - **Single-Threaded:** No parallel processing for multiple trading pairs or exchanges
   - **Resource Constraints:** No connection pooling, memory management, or resource limits
   - **Horizontal Scaling:** No distributed architecture for load balancing across multiple instances

**Production Architecture Evolution:**

1. **Microservices Architecture:**
   - **API Gateway Layer:** Centralized routing and load balancing using Kong or Nginx
   - **Order Management Service:** Dedicated service for order placement, cancellation, and tracking
   - **Data Pipeline Service:** Specialized service for market data ingestion and processing
   - **Market Data Service:** WebSocket connections and real-time data distribution
   - **Risk Engine:** Real-time position monitoring and risk calculations using Redis
   - **Storage Layer:** Dual-tier storage with S3 for cold data and database for hot data

2. **Message Queue Architecture:**
   - **Apache Kafka/RabbitMQ:** For reliable message passing between services with back-pressure handling
   - **Event Sourcing:** All trading events stored as immutable logs for audit and replay
   - **CQRS Pattern:** Separate read/write models for order management and analytics

3. **Real-time Data Pipeline:**
   - **WebSocket Connections:** Persistent connections with automatic reconnection and heartbeat monitoring
   - **Redis Pub/Sub:** Real-time price and order book distribution to multiple consumers
   - **Apache Kafka Streams:** Real-time order book processing and cross-exchange aggregation
   - **Apache Flink:** Complex event processing for market analysis and synthetic spread calculation

4. **High Availability Components:**
   - **Load Balancers:** HAProxy/Nginx for API traffic distribution and health checking
   - **Database Clustering:** PostgreSQL with read replicas and TimescaleDB clustering for time-series data
   - **Caching Layer:** Redis Cluster for session management and hot data with automatic failover
   - **CDN:** CloudFront for static content and API acceleration

5. **Monitoring and Observability:**
   - **Prometheus + Grafana:** Metrics collection and visualization with custom dashboards
   - **ELK Stack:** Centralized logging and log analysis with structured logging
   - **Jaeger:** Distributed tracing for request flows and performance analysis
   - **Health Checks:** Kubernetes liveness/readiness probes for automatic recovery

6. **Container Orchestration:**
   - **Kubernetes:** Auto-scaling, rolling deployments, service discovery, and resource management
   - **Docker:** Containerized microservices with resource limits and security isolation
   - **Helm Charts:** Infrastructure as code for deployment and configuration management

### Error Handling & Resilience

**Comprehensive Error Handling Strategy:**

1. **Exchange API Error Handling:**
   - **Circuit Breaker Pattern:** Implement circuit breakers that automatically isolate failing exchanges to prevent cascading failures
   - **Exponential Backoff with Jitter:** Failed requests trigger exponential backoff with random jitter to avoid thundering herd problems
   - **Retry Logic:** Intelligent retry mechanisms that distinguish between retryable and non-retryable errors

2. **WebSocket Connection Resilience:**
   - **Automatic Reconnection:** WebSocket connections automatically reconnect with exponential backoff when connections are lost
   - **Heartbeat Monitoring:** Regular ping/pong messages to detect connection health and trigger reconnection
   - **Session State Management:** Persistent state tracking to resume connections from the last known good state

3. **State Consistency Management:**
   - **Event Sourcing:** Every order and execution event is persisted in an immutable event log
   - **CQRS Pattern:** Separate read and write models with eventual consistency for better performance
   - **Event Replay:** Ability to rebuild system state from event logs for debugging and audit purposes

4. **Multi-Exchange Redundancy:**
   - **Exchange Failover Strategy:** Automatic failover between exchanges when primary venues experience issues
   - **Load Distribution:** Intelligent routing of orders across multiple exchanges based on availability and performance
   - **Health Monitoring:** Continuous monitoring of exchange health and automatic isolation of problematic venues

5. **Data Consistency Guarantees:**
   - **Saga Pattern:** For complex multi-exchange operations that require coordination
   - **Two-Phase Commit:** For critical order placement operations that must be atomic
   - **Eventual Consistency:** For non-critical data like market data and analytics
   - **Compensation Actions:** Automatic rollback mechanisms for failed operations

6. **Health Monitoring and Alerting:**
   - **Comprehensive Health Checks:** Monitoring of API latency, WebSocket connection status, order success rates, and data freshness
   - **Automated Alerting:** Proactive alerting based on SLO violations with appropriate escalation paths
   - **Synthetic Monitoring:** Regular synthetic transactions to validate system functionality

This comprehensive strategy ensures the system can handle exchange failures gracefully, maintain data consistency, and provide reliable trading operations even under adverse conditions.