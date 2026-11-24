"""
Symbol normalization helpers.
Ensures all market-data paths (WS/REST) emit identical canonical symbols.
"""


NIFTY50 = "NSE|Nifty 50"
INDIA_VIX = "NSE|INDIA VIX"
NIFTY_BANK = "NSE|Nifty Bank"

_ALIASES = {
    "NSE_INDEX|NIFTY 50": NIFTY50,
    "NSE|NIFTY 50": NIFTY50,
    "NIFTY_50": NIFTY50,
    "NSE_INDEX|INDIA VIX": INDIA_VIX,
    "NSE|INDIA VIX": INDIA_VIX,
    "INDIA_VIX": INDIA_VIX,
    "NSE_INDEX|NIFTY BANK": NIFTY_BANK,
    "NSE|NIFTY BANK": NIFTY_BANK,
    "NIFTY_BANK": NIFTY_BANK,
}


def normalize_symbol(symbol: str) -> str:
    """Returns canonical symbol identifiers for index symbols."""
    if not symbol:
        return symbol
    return _ALIASES.get(symbol.upper(), symbol)


def is_nifty50(symbol: str) -> bool:
    return normalize_symbol(symbol) == NIFTY50


def is_india_vix(symbol: str) -> bool:
    return normalize_symbol(symbol) == INDIA_VIX
