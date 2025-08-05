import pandas as pd
from pathlib import Path

# Find all parquet files and group by exchange
data_dir = Path("data")
parquet_files = list(data_dir.rglob("*.parquet"))

if parquet_files:
    print(f"Found {len(parquet_files)} total files")
    
    # Group files by exchange
    by_exchange = {}
    for file in parquet_files:
        parts = str(file).split('\\')
        for part in parts:
            if part.startswith('exchange='):
                exchange = part.split('=')[1]
                if exchange not in by_exchange:
                    by_exchange[exchange] = []
                by_exchange[exchange].append(file)
                break
    
    print(f"Exchanges found: {list(by_exchange.keys())}")
    print("=" * 60)
    
    # Show data from each exchange
    for exchange, files in by_exchange.items():
        print(f"\n{exchange.upper()} EXCHANGE:")
        print("-" * 40)
        
        # Read first file from this exchange
        file_path = files[0]
        print(f"File: {file_path.name}")
        
        df = pd.read_parquet(file_path)
        row = df.iloc[0]
        
        bids = row['bids']  # Array of [price, size] pairs
        asks = row['asks']  # Array of [price, size] pairs
        
        # Calculate mid price from best bid/ask
        if len(bids) > 0 and len(asks) > 0:
            best_bid = bids[0][0] if len(bids[0]) > 0 else 0
            best_ask = asks[0][0] if len(asks[0]) > 0 else 0
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            spread_bps = (spread / mid_price) * 10000 if mid_price > 0 else 0
        else:
            mid_price = 0
            spread = 0
            spread_bps = 0
        
        # Handle different timestamp fields
        if 'ts_capture_ns' in row:
            timestamp = pd.to_datetime(row['ts_capture_ns'], unit='ns')
        elif 'ts_venue_ns' in row:
            timestamp = pd.to_datetime(row['ts_venue_ns'], unit='ns')
        elif 'ts_ns' in row:
            timestamp = pd.to_datetime(row['ts_ns'], unit='ns')
        else:
            timestamp = "Unknown"
        
        # Handle different pair/symbol fields
        if 'pair' in row:
            pair = row['pair']
        elif 'symbol' in row:
            pair = row['symbol']
        else:
            pair = "Unknown"
        
        print(f"Timestamp: {timestamp}")
        print(f"Pair: {pair}")
        print(f"Mid Price: ${mid_price:,.2f}")
        print(f"Spread: {spread:.6f} ({spread_bps:.4f} bps)")
        print(f"Depth: {row['bid_count']} bids x {row['ask_count']} asks")
        
        print(f"\nTop 3 Bids (Price @ Size):")
        for i, bid in enumerate(bids[:3]):
            if len(bid) >= 2:
                print(f"  {i+1}. ${bid[0]:,.2f} @ {bid[1]:.6f}")
        
        print(f"\nTop 3 Asks (Price @ Size):")
        for i, ask in enumerate(asks[:3]):
            if len(ask) >= 2:
                print(f"  {i+1}. ${ask[0]:,.2f} @ {ask[1]:.6f}")

else:
    print("No parquet files found!")