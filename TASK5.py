#!/usr/bin/env python3
"""
Task 5: Historical L2 Order Book Data Persistence for Backtesting

A simplified data pipeline that captures and stores L2 order book snapshots 
to AWS S3 as Parquet files for future backtesting analysis.

Key Features:
- Captures full L2 order book data from multiple exchanges
- Stores data as Parquet files partitioned by exchange/date/hour
- Uploads to AWS S3 with validation
- Configurable capture frequency and depth
- Uses venue timestamps with local fallback

Usage Examples:
    # Basic capture to S3
    python TASK5.py --exch binance --pair BTCUSDT --s3-bucket my-bucket
    
    # Full depth capture with custom interval
    python TASK5.py --exch all --pair BTCUSDT --depth max --interval 1 --s3-bucket my-bucket
    
    # Long-running capture
    python TASK5.py --exch bybit --pair ETHUSDT --minutes 60 --s3-bucket my-bucket
"""

import asyncio
import aiohttp
import time
import json
import os
import argparse
import datetime as dt
from typing import List, Tuple, Dict, Any, Optional, Union
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from dataclasses import dataclass
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Exchange Connectors
class ExchangeConnector:
    """Simple exchange connector for L2 order book data"""
    
    @staticmethod
    def normalize_symbol(symbol: str, exchange: str) -> str:
        """Normalize symbol for exchange"""
        s = symbol.upper().replace(" ", "").replace("_", "-").replace("/", "-")
        if "-" in s:
            parts = [p for p in s.split("-") if p]
            if len(parts) >= 2:
                base, quote = parts[0], parts[1]
            else:
                base, quote = parts[0], "USDT"
        else:
            if s.endswith("USDT"):
                base, quote = s[:-4], "USDT"
            elif s.endswith("USD"):
                base, quote = s[:-3], "USD"
            else:
                base, quote = s, "USDT"
        ex = exchange.lower()
        if ex in ["binance", "bybit"]:
            return f"{base}{quote}"
        elif ex == "kucoin":
            return f"{base}-{quote}"
        elif ex == "deribit":
            if "BTC" in base:
                return "BTC-PERPETUAL"
            elif "ETH" in base:
                return "ETH-PERPETUAL"
            else:
                return "BTC-PERPETUAL"
        else:
            return f"{base}-{quote}"

    @staticmethod
    async def get_l2_orderbook(session: aiohttp.ClientSession, exchange: str, symbol: str, 
                              depth: Union[int, str] = 100) -> Dict[str, Any]:
        """Get L2 order book from exchange"""
        normalized_symbol = ExchangeConnector.normalize_symbol(symbol, exchange)
        if exchange == "binance":
            return await ExchangeConnector._binance_l2(session, normalized_symbol, depth)
        elif exchange == "bybit":
            return await ExchangeConnector._bybit_l2(session, normalized_symbol, depth)
        elif exchange == "kucoin":
            return await ExchangeConnector._kucoin_l2(session, normalized_symbol, depth)
        elif exchange == "deribit":
            return await ExchangeConnector._deribit_l2(session, normalized_symbol, depth)
        else:
            raise ValueError(f"Unsupported exchange: {exchange}")
    
    @staticmethod
    async def _binance_l2(session: aiohttp.ClientSession, symbol: str, depth: Union[int, str]) -> Dict[str, Any]:
        """Binance L2 order book"""
        if depth == "max":
            limit = 5000  # Binance max
        else:
            limit = min(int(depth), 5000)
        url = "https://api.binance.com/api/v3/depth"
        params = {"symbol": symbol, "limit": limit}
        async with session.get(url, params=params) as r:
            if r.status != 200:
                raise RuntimeError(f"Binance HTTP {r.status}: {await r.text()}")
            data = await r.json()
        return {
            "exchange": "binance",
            "symbol": symbol,
            "timestamp": int(time.time() * 1000),  # Binance doesn't provide timestamp in depth
            "bids": [[float(p), float(q)] for p, q in data.get("bids", [])],
            "asks": [[float(p), float(q)] for p, q in data.get("asks", [])]
        }
    
    @staticmethod
    async def _bybit_l2(session: aiohttp.ClientSession, symbol: str, depth: Union[int, str]) -> Dict[str, Any]:
        """Bybit L2 order book"""
        if depth == "max":
            limit = 500  # Bybit max
        else:
            limit = min(int(depth), 500)
        url = "https://api.bybit.com/v5/market/orderbook"
        params = {"category": "spot", "symbol": symbol, "limit": limit}
        async with session.get(url, params=params) as r:
            if r.status != 200:
                raise RuntimeError(f"Bybit HTTP {r.status}: {await r.text()}")
            data = await r.json()
        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit error: {data}")
        result = data.get("result", {})
        return {
            "exchange": "bybit",
            "symbol": symbol,
            "timestamp": int(result.get("ts", time.time() * 1000)),
            "bids": [[float(p), float(q)] for p, q in result.get("b", [])],
            "asks": [[float(p), float(q)] for p, q in result.get("a", [])]
        }
    
    @staticmethod
    async def _kucoin_l2(session: aiohttp.ClientSession, symbol: str, depth: Union[int, str]) -> Dict[str, Any]:
        """KuCoin L2 order book"""
        url = "https://api.kucoin.com/api/v1/market/orderbook/level2_100"
        params = {"symbol": symbol}
        async with session.get(url, params=params) as r:
            if r.status != 200:
                raise RuntimeError(f"KuCoin HTTP {r.status}: {await r.text()}")
            data = await r.json()
        if data.get("code") != "200000":
            raise RuntimeError(f"KuCoin error: {data}")
        result = data.get("data", {})
        return {
            "exchange": "kucoin",
            "symbol": symbol,
            "timestamp": int(result.get("time", time.time() * 1000)),
            "bids": [[float(p), float(q)] for p, q in result.get("bids", [])],
            "asks": [[float(p), float(q)] for p, q in result.get("asks", [])]
        }
    
    @staticmethod
    async def _deribit_l2(session: aiohttp.ClientSession, symbol: str, depth: Union[int, str]) -> Dict[str, Any]:
        """Deribit L2 order book"""
        if depth == "max":
            depth_param = 1000  # Deribit max
        else:
            depth_param = min(int(depth), 1000)
        url = "https://www.deribit.com/api/v2/public/get_order_book"
        params = {"instrument_name": symbol, "depth": depth_param}
        async with session.get(url, params=params) as r:
            if r.status != 200:
                raise RuntimeError(f"Deribit HTTP {r.status}: {await r.text()}")
            data = await r.json()
        if "error" in data:
            raise RuntimeError(f"Deribit error: {data['error']}")
        result = data.get("result", {})
        return {
            "exchange": "deribit",
            "symbol": symbol,
            "timestamp": int(result.get("timestamp", time.time() * 1000)),
            "bids": [[float(p), float(q)] for p, q in result.get("bids", [])],
            "asks": [[float(p), float(q)] for p, q in result.get("asks", [])]
        }

# Data Structures
@dataclass
class L2Snapshot:
    """L2 order book snapshot with venue timestamp"""
    exchange: str
    symbol: str
    timestamp: int  # Venue timestamp in milliseconds
    bids: List[List[float]]  # Full depth bids [[price, quantity], ...]
    asks: List[List[float]]  # Full depth asks [[price, quantity], ...]
    capture_time: int = None  # Local capture time for monitoring
    
    def __post_init__(self):
        if self.capture_time is None:
            self.capture_time = int(time.time() * 1000)

# Local + S3 Backend
class LocalStagingBackend:
    """Local Parquet storage with optional S3 upload"""
    
    def __init__(self, local_base: str = "data", s3_bucket: str = None, s3_prefix: str = "orderbooks", s3_region: str = None):
        self.local_base = local_base
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix
        self.s3_region = s3_region or "us-east-1"
        self._s3_client = None
        
        # Statistics
        self.files_written = 0
        self.total_rows = 0
        self.failed_writes = 0
        self.failed_uploads = 0
        
        # S3 upload queue for non-blocking uploads
        self.s3_upload_queue = queue.Queue()
        self.s3_uploaded = 0
        self.s3_failed = 0
        self.stop_flag = threading.Event()
        
        # Initialize S3 if configured
        if self.s3_bucket:
            self._get_s3_client()
            if self._s3_client:
                self._check_bucket()
                # Start S3 upload worker
                threading.Thread(target=self._s3_worker, daemon=True).start()
                logger.info(f"Local+S3 backend initialized: local={local_base}, s3={s3_bucket}")
            else:
                logger.warning("S3 client failed to initialize, using local-only mode")
        else:
            logger.info(f"Local-only backend initialized: {local_base}")

    def _get_s3_client(self):
        """Initialize S3 client"""
        if self._s3_client is None:
            try:
                import boto3
                self._s3_client = boto3.client('s3', region_name=self.s3_region)
                logger.info(f"S3 client initialized for bucket: {self.s3_bucket} region: {self.s3_region}")
            except ImportError:
                logger.error("boto3 not installed. Install with: pip install boto3")
                return None
        return self._s3_client

    def _check_bucket(self):
        """Check if S3 bucket exists"""
        client = self._get_s3_client()
        if client:
            try:
                client.head_bucket(Bucket=self.s3_bucket)
            except Exception as e:
                logger.error(f"S3 bucket {self.s3_bucket} not accessible: {e}")
                self._s3_client = None

    def _s3_worker(self):
        """Background S3 upload worker"""
        while not self.stop_flag.is_set():
            try:
                local_path, s3_key = self.s3_upload_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._s3_client.upload_file(local_path, self.s3_bucket, s3_key)
                self.s3_uploaded += 1
                logger.debug(f"Uploaded to S3: {s3_key}")
            except Exception as e:
                self.s3_failed += 1
                logger.warning(f"S3 upload failed: {s3_key} ({e})")
            finally:
                self.s3_upload_queue.task_done()

    def _get_local_path(self, exchange: str, pair: str, timestamp: int) -> str:
        """Generate local file path"""
        dt_obj = dt.datetime.fromtimestamp(timestamp / 1000, tz=dt.timezone.utc)
        date_str = dt_obj.strftime("%Y-%m-%d")
        hour_str = dt_obj.strftime("%H")
        
        # Local path: data/exchange/pair/date/hour/snapshot_timestamp.parquet
        local_dir = os.path.join(self.local_base, exchange, pair, date_str, hour_str)
        os.makedirs(local_dir, exist_ok=True)
        
        fname = f"snapshot_{timestamp}.parquet"
        return os.path.join(local_dir, fname)

    def _get_s3_key(self, exchange: str, pair: str, timestamp: int) -> str:
        """Generate S3 key"""
        dt_obj = dt.datetime.fromtimestamp(timestamp / 1000, tz=dt.timezone.utc)
        date_str = dt_obj.strftime("%Y-%m-%d")
        hour_str = dt_obj.strftime("%H")
        minute_str = dt_obj.strftime("%M")
        
        # S3 key: prefix/exchange=exch/pair=PAIR/date=date/hour=hour/part-minute-timestamp.parquet
        s3_key = f"{self.s3_prefix}/exchange={exchange}/pair={pair}/date={date_str}/hour={hour_str}/part-{minute_str}-{timestamp}.parquet"
        return s3_key

    async def write_snapshots(self, snapshots: List[L2Snapshot]) -> bool:
        """Write snapshots locally and queue for S3 upload"""
        if not snapshots:
            return True
        
        try:
            # Group by exchange and pair
            by_exchange_pair = {}
            for snap in snapshots:
                k = (snap.exchange, snap.symbol)
                if k not in by_exchange_pair:
                    by_exchange_pair[k] = []
                by_exchange_pair[k].append(snap)
            
            # Write each exchange/pair separately
            for (exchange, pair), exchange_snapshots in by_exchange_pair.items():
                success = await self._write_exchange_file(exchange, pair, exchange_snapshots)
                if not success:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write snapshots: {e}")
            self.failed_writes += 1
            return False

    async def _write_exchange_file(self, exchange: str, pair: str, snapshots: List[L2Snapshot]) -> bool:
        """Write snapshots for a single exchange/pair"""
        try:
            # Convert to DataFrame with dual timestamps
            records = []
            for snap in snapshots:
                # Ensure bids/asks are float[][]
                bids = [[float(p), float(q)] for p, q in snap.bids]
                asks = [[float(p), float(q)] for p, q in snap.asks]
                
                # Dual timestamps
                ts_venue_ns = snap.timestamp * 1_000_000 if snap.timestamp else None
                ts_capture_ns = snap.capture_time * 1_000_000 if snap.capture_time else None
                ts_source = 'venue' if snap.timestamp and snap.timestamp != 0 else 'local_fallback'
                
                records.append({
                    "ts_venue_ns": ts_venue_ns,
                    "ts_capture_ns": ts_capture_ns,
                    "ts_source": ts_source,
                    "exchange": snap.exchange,
                    "pair": pair,
                    "bids": bids,
                    "asks": asks,
                    "bid_count": len(bids),
                    "ask_count": len(asks)
                })
            
            df = pd.DataFrame(records)
            
            # Define schema
            schema = pa.schema([
                pa.field("ts_venue_ns", pa.int64()),
                pa.field("ts_capture_ns", pa.int64()),
                pa.field("ts_source", pa.string()),
                pa.field("exchange", pa.string()),
                pa.field("pair", pa.string()),
                pa.field("bids", pa.list_(pa.list_(pa.float64()))),
                pa.field("asks", pa.list_(pa.list_(pa.float64()))),
                pa.field("bid_count", pa.int32()),
                pa.field("ask_count", pa.int32())
            ])
            
            # Create Parquet table
            table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
            
            # Write to local file
            local_path = self._get_local_path(exchange, pair, snapshots[0].timestamp)
            pq.write_table(table, local_path, compression="snappy")
            
            # Update statistics
            self.files_written += 1
            self.total_rows += len(snapshots)
            
            logger.info(f"Saved {len(snapshots)} snapshots to {local_path}")
            
            # Queue for S3 upload (non-blocking)
            if self._s3_client:
                s3_key = self._get_s3_key(exchange, pair, snapshots[0].timestamp)
                self.s3_upload_queue.put((local_path, s3_key))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write {exchange} file: {e}")
            self.failed_writes += 1
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get backend statistics"""
        stats = {
            "backend": "local_staging",
            "files_written": self.files_written,
            "total_rows": self.total_rows,
            "failed_writes": self.failed_writes,
            "local_base": self.local_base
        }
        
        if self._s3_client:
            stats.update({
                "s3_bucket": self.s3_bucket,
                "s3_uploaded": self.s3_uploaded,
                "s3_failed": self.s3_failed,
                "s3_queue_size": self.s3_upload_queue.qsize()
            })
        
        return stats

    def cleanup(self):
        """Cleanup resources"""
        self.stop_flag.set()

# S3 Parquet Backend 
class S3ParquetBackend:
    """Legacy S3-only backend - now wraps LocalStagingBackend"""
    
    def __init__(self, s3_bucket: str, s3_prefix: str = "orderbooks", s3_region: str = None, pair: str = None):
        # Create LocalStagingBackend with S3 enabled
        self.backend = LocalStagingBackend(
            local_base="data",
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix,
            s3_region=s3_region
        )
        self.s3_bucket = s3_bucket  # Keep for compatibility

    async def write_snapshots(self, snapshots: List[L2Snapshot]) -> bool:
        return await self.backend.write_snapshots(snapshots)

    def get_stats(self) -> Dict[str, Any]:
        return self.backend.get_stats()

# Main Capture Engine
class L2CaptureEngine:
    """Main L2 order book capture engine"""
    
    def __init__(self, exchanges: List[str], pair: str, depth: Union[int, str], 
                 interval: float, backend: LocalStagingBackend, s3_region: str = None):
        self.exchanges = exchanges
        self.pair = pair
        self.depth = depth
        self.interval = interval
        self.backend = backend
        self.s3_region = s3_region
        self.snapshots_captured = 0
        self.snapshots_failed = 0
        self.start_time = None
        self.session = None
    
    async def _setup_session(self):
        """Setup HTTP session"""
        timeout = aiohttp.ClientTimeout(total=10)
        headers = {"User-Agent": "L2-Snapshotter-S3/1.0"}
        self.session = aiohttp.ClientSession(timeout=timeout, headers=headers)
    
    async def _capture_single_exchange(self, exchange: str) -> Optional[L2Snapshot]:
        """Capture L2 snapshot from a single exchange"""
        try:
            data = await ExchangeConnector.get_l2_orderbook(self.session, exchange, self.pair, self.depth)
            
            # Venue timestamp
            ts_venue = data.get("timestamp", int(time.time() * 1000))
            # ts_source
            ts_source = "venue" if "timestamp" in data else "local_fallback"
            # Normalize bids/asks
            bids = [[float(p), float(q)] for p, q in data["bids"]]
            asks = [[float(p), float(q)] for p, q in data["asks"]]
            snapshot = L2Snapshot(
                exchange=data["exchange"],
                symbol=data["symbol"],
                timestamp=ts_venue,
                bids=bids,
                asks=asks,
                capture_time=int(time.time() * 1000)
            )
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Failed to capture {exchange} {self.pair}: {e}")
            return None
    
    async def _capture_round(self) -> List[L2Snapshot]:
        """Capture snapshots from all exchanges"""
        tasks = [self._capture_single_exchange(exchange) for exchange in self.exchanges]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        snapshots = []
        for result in results:
            if isinstance(result, L2Snapshot):
                snapshots.append(result)
                self.snapshots_captured += 1
            else:
                self.snapshots_failed += 1
        
        return snapshots
    
    async def run(self, duration_minutes: int = 0):
        """Run the capture engine"""
        self.start_time = time.time()
        end_time = self.start_time + (duration_minutes * 60) if duration_minutes > 0 else float('inf')
        
        logger.info(f"Starting L2 capture for {self.exchanges}")
        logger.info(f"Pair: {self.pair}, Depth: {self.depth}, Interval: {self.interval}s")
        logger.info(f"S3 Bucket: {self.backend.s3_bucket}")
        
        # Setup session
        await self._setup_session()
        
        try:
            next_tick = time.time()
            
            while time.time() < end_time:
                # Capture snapshots
                snapshots = await self._capture_round()
                
                # Write to S3
                if snapshots:
                    await self.backend.write_snapshots(snapshots)
                
                # Log progress every 30 seconds
                if int(time.time()) % 30 == 0:
                    await self._log_progress()
                
                # Schedule next tick
                next_tick += self.interval
                sleep_time = max(0.0, next_tick - time.time())
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    
        finally:
            if self.session:
                await self.session.close()
    
    async def _log_progress(self):
        """Log current progress and statistics"""
        elapsed = time.time() - self.start_time
        rate = (self.snapshots_captured + self.snapshots_failed) / elapsed if elapsed > 0 else 0
        
        backend_stats = self.backend.get_stats()
        
        logger.info(f"Progress: {self.snapshots_captured} captured, {self.snapshots_failed} failed, {rate:.1f}/sec")
        logger.info(f"S3: {backend_stats}")

# CLI
def main():
    parser = argparse.ArgumentParser(
        description="Task 5: L2 Order Book Data Persistence to S3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic capture to S3
  python TASK5.py --exch binance --pair BTCUSDT --s3-bucket my-bucket
  
  # Full depth capture with custom interval
  python TASK5.py --exch all --pair BTCUSDT --depth max --interval 1 --s3-bucket my-bucket
  
  # Long-running capture
  python TASK5.py --exch bybit --pair ETHUSDT --minutes 60 --s3-bucket my-bucket
        """
    )
    parser.add_argument("--exch", 
                       choices=["binance", "bybit", "kucoin", "deribit", "all"],
                       default="binance",
                       help="Exchange(s) to capture")
    parser.add_argument("--pair", 
                       default="BTCUSDT",
                       help="Trading pair")
    parser.add_argument("--depth", 
                       default="max",
                       help="Order book depth (number or 'max' for full depth)")
    parser.add_argument("--interval", 
                       type=float, 
                       default=1.0,
                       help="Capture interval in seconds")
    parser.add_argument("--s3-bucket",
                       required=True,
                       help="S3 bucket for upload")
    parser.add_argument("--s3-prefix",
                       default="orderbooks",
                       help="S3 prefix for uploaded files")
    parser.add_argument("--s3-region",
                       default=None,
                       help="S3 region (default: us-east-1 or env S3_REGION)")
    parser.add_argument("--minutes",
                       type=int,
                       default=0,
                       help="Run duration in minutes (0 = unlimited)")
    args = parser.parse_args()
    if args.exch == "all":
        exchanges = ["binance", "bybit", "kucoin", "deribit"]
    else:
        exchanges = [args.exch]
    backend = LocalStagingBackend(args.s3_bucket, args.s3_prefix, args.s3_region, args.pair)
    engine = L2CaptureEngine(exchanges, args.pair, args.depth, args.interval, backend, args.s3_region)
    try:
        asyncio.run(engine.run(duration_minutes=args.minutes))
    except KeyboardInterrupt:
        logger.info("Capture interrupted")
    except Exception as e:
        logger.error(f"Capture failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    import sys
    import threading
    import queue
    import websockets
    import numpy as np
    import pytz
    import shutil
    import subprocess
    import concurrent.futures

    # --- CONFIG ---
    import os
    import time
    import datetime as dt
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import logging

    # Only run this mode if --binance-ws is passed
    if "--binance-ws" in sys.argv:
        import asyncio
        import json
        
        PAIR = os.environ.get("PAIR", "BTCUSDT").upper()
        S3_BUCKET = os.environ.get("S3_BUCKET", "my-crypto-data-2025")
        S3_REGION = os.environ.get("S3_REGION", "us-east-1")
        EXCHANGE = "Binance"
        CAPTURE_INTERVAL = 1.0  # seconds
        LOCAL_BASE = f"data/{PAIR}"
        WS_URL = f"wss://stream.binance.com:9443/ws/{PAIR.lower()}@depth20@100ms"
        LOG_EVERY = 60  # seconds

        # Setup logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        logger = logging.getLogger("binance_ws")

        # Use LocalStagingBackend for consistency
        backend = LocalStagingBackend(
            local_base="data",
            s3_bucket=S3_BUCKET if S3_BUCKET != "my-crypto-data-2025" else None,  # Only use if explicitly set
            s3_prefix="orderbooks",
            s3_region=S3_REGION
        )

        # Statistics
        local_saved = 0
        stop_flag = threading.Event()

        # Utility: get UTC timestamp (ns)
        def utc_now_ns():
            return int(time.time() * 1_000_000_000)

        # Main async loop
        async def main_loop():
            global local_saved
            logger.info(f"Connecting to {WS_URL}")
            async with websockets.connect(WS_URL, ping_interval=None) as ws:
                last_save = 0
                stats_start = time.time()
                local_saved = 0
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5)
                        data = json.loads(msg)
                        now = time.time()
                        if 'bids' in data and 'asks' in data:
                            # Only save once per second
                            if now - last_save >= CAPTURE_INTERVAL:
                                ts_ns = utc_now_ns()
                                
                                # Create snapshot with venue timestamp
                                snapshot = L2Snapshot(
                                    exchange=EXCHANGE,
                                    symbol=PAIR,
                                    timestamp=data.get('E', int(time.time() * 1000)),  # Use Binance event time if available
                                    bids=[[float(p), float(q)] for p, q in data['bids']],
                                    asks=[[float(p), float(q)] for p, q in data['asks']],
                                    capture_time=int(time.time() * 1000)
                                )
                                
                                # Write using backend (local + optional S3)
                                await backend.write_snapshots([snapshot])
                                local_saved += 1
                                last_save = now
                        
                        # Logging every minute
                        if int(now - stats_start) % LOG_EVERY == 0 and now - stats_start > 0:
                            backend_stats = backend.get_stats()
                            logger.info(f"Snapshots saved: {local_saved}, Backend stats: {backend_stats}")
                            
                    except asyncio.TimeoutError:
                        logger.warning("WebSocket timeout, reconnecting...")
                        break
                    except Exception as e:
                        logger.error(f"Error in main loop: {e}")
                        await asyncio.sleep(1)

        # Run for at least 10 minutes
        async def run_for_10min():
            global local_saved
            start = time.time()
            while time.time() - start < 600:
                try:
                    await main_loop()
                except Exception as e:
                    logger.error(f"Main loop error: {e}")
                    await asyncio.sleep(2)
            stop_flag.set()
            backend.cleanup()
            backend_stats = backend.get_stats()
            logger.info(f"Finished. Snapshots saved: {local_saved}, Backend stats: {backend_stats}")

        asyncio.run(run_for_10min())
        sys.exit(0)

    main() 