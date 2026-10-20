"""
screener/src/config.py - Centralized configuration settings for StockSentinel screener and ingestion engine.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Project Root Resolution
SRC_DIR = Path(__file__).resolve().parent
SCREENER_DIR = SRC_DIR.parent
PROJECT_ROOT = SCREENER_DIR.parent

# Load .env if present, otherwise fallback to .env.example
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    example_path = PROJECT_ROOT / ".env.example"
    if example_path.exists():
        load_dotenv(dotenv_path=example_path)

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "stocksentinel")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{DB_HOST}:{DB_PORT}/{POSTGRES_DB}"
)


# Data & Cache Directories
DATA_DIR = Path(os.getenv("DATA_DIR", str(SCREENER_DIR / "data"))).resolve()
PARQUET_DIR = Path(os.getenv("PARQUET_DIR", str(DATA_DIR / "parquet"))).resolve()
UNIVERSE_SEED_FILE = Path(os.getenv("UNIVERSE_SEED_FILE", str(DATA_DIR / "universe" / "russell3000_sp1500.json"))).resolve()

# Downloader Settings
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "25"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "3.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
BACKOFF_BASE = float(os.getenv("BACKOFF_BASE", "2.0"))
BACKOFF_MAX = float(os.getenv("BACKOFF_MAX", "30.0"))

# Sync Windows
COLD_START_DAYS = int(os.getenv("COLD_START_DAYS", "730"))
DELTA_DAYS = int(os.getenv("DELTA_DAYS", "7"))

# Telegram Alerting (M4 – Feature F21/F22/F23)
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED: bool = os.getenv("TELEGRAM_ENABLED", "false").lower() in ("1", "true", "yes")

# Web Application Base URL (used for deep-link chart URLs in Telegram cards)
WEB_APP_BASE_URL: str = os.getenv("WEB_APP_BASE_URL", "https://stocksentinel-web.onrender.com")
