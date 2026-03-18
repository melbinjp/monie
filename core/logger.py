"""
Primitive 1: World-Class Contextual Logging System
Replaces all print() across the codebase with structured, rotated, leveled logging.
Every log line carries: ISO timestamp | module.strategy | severity | message
"""
import os
import logging
from logging.handlers import RotatingFileHandler

# Ensure logs directory exists
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

# Shared file handler (all modules write to same rotating file)
_file_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "monie.log"),
    maxBytes=10_000_000,  # 10 MB per file
    backupCount=5,        # Keep 5 backups = 50 MB max disk
    encoding="utf-8"
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))

# Console handler (INFO+ only, clean output for systemd journal)
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter("%(message)s"))

# Root monie logger
_root = logging.getLogger("monie")
_root.setLevel(logging.DEBUG)
if not _root.handlers:
    _root.addHandler(_file_handler)
    _root.addHandler(_console_handler)


def get_logger(name: str, strategy_name: str = None) -> logging.Logger:
    """
    Returns a contextual logger for any module.
    
    Usage:
        from core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("CE Sold @ ₹185.5")
        
    With strategy context:
        logger = get_logger(__name__, strategy_name="Straddle")
        # Output: 2026-03-14 09:23:01 | monie.straddle.monitor | INFO | CE Sold
    """
    if strategy_name:
        full_name = f"monie.{strategy_name.lower()}.{name.split('.')[-1]}"
    else:
        full_name = f"monie.{name.split('.')[-1]}"
    
    logger = logging.getLogger(full_name)
    
    # Prevent duplicate handlers if get_logger called multiple times
    if not logger.handlers and not logger.parent.handlers:
        logger.addHandler(_file_handler)
        logger.addHandler(_console_handler)
    
    return logger
