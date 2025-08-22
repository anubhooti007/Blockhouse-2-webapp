"""
Environment and secrets management for the Streamlit webapp.

Loads secrets from .env in project root and/or Streamlit secrets.toml.
"""
import os
import sys
from pathlib import Path
from typing import Optional

# Add project root to path to import dotenv
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    _DOTENV_AVAILABLE = True
except ImportError:
    _DOTENV_AVAILABLE = False

try:
    import streamlit as st
    _STREAMLIT_AVAILABLE = True
except ImportError:
    _STREAMLIT_AVAILABLE = False


def load_env() -> None:
    """Load environment variables from .env file in project root."""
    if _DOTENV_AVAILABLE:
        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path)


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get a secret value, checking both environment variables and Streamlit secrets.
    
    Args:
        key: Secret key name
        default: Default value if secret not found
        
    Returns:
        Secret value or default
    """
    # First check environment variables
    value = os.environ.get(key)
    if value:
        return value
    
    # Then check Streamlit secrets if available
    if _STREAMLIT_AVAILABLE:
        try:
            if hasattr(st, 'secrets') and key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
    
    return default


def is_testnet(exchange: str) -> bool:
    """Check if exchange supports testnet mode."""
    testnet_exchanges = {"binance", "bybit", "deribit"}
    return exchange.lower() in testnet_exchanges


def get_exchange_list() -> list[str]:
    """Get list of supported exchanges."""
    return [
        "binance",
        "bybit", 
        "deribit",
        "kucoin",
        "bitmart",
        "okx",
        "hyperliquid"
    ]


def get_trading_exchanges() -> list[str]:
    """Get list of exchanges that support trading."""
    return [
        "binance",
        "bybit",
        "deribit", 
        "kucoin",
        "bitmart",
        "okx"
    ]


# Initialize environment on import
load_env()
