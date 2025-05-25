# app/config.py
import os
from pathlib import Path
import logging

# --- Core Application Settings ---
DEBUG_LOGGING_ENV = os.getenv("DEBUG_LOGGING", "false")
DEBUG_LOGGING = DEBUG_LOGGING_ENV.lower() == "true"

# --- Transcription Engine Configuration ---
TRANSCRIPTION_ENGINE = os.getenv("TRANSCRIPTION_ENGINE", "faster-whisper").lower()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base") # Used by both engines
DEVICE = os.getenv("DEVICE", "cpu") # Used by both engines
# faster-whisper specific
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "default") # Only for faster-whisper

# --- Podcast Feed Configuration ---
PODCAST_FEEDS_ENV = os.getenv("PODCAST_FEEDS", "")
podcast_urls = []
if PODCAST_FEEDS_ENV:
    podcast_urls = [url.strip() for url in PODCAST_FEEDS_ENV.split(';') if url.strip()]

CHECK_INTERVAL_SECONDS_ENV = os.getenv("CHECK_INTERVAL_SECONDS", "3600")
try:
    CHECK_INTERVAL_SECONDS = int(CHECK_INTERVAL_SECONDS_ENV)
except ValueError:
    logging.warning(f"Invalid CHECK_INTERVAL_SECONDS: {CHECK_INTERVAL_SECONDS_ENV}. Defaulting to 3600.")
    CHECK_INTERVAL_SECONDS = 3600

LOOKBACK_DAYS_ENV = os.getenv("LOOKBACK_DAYS", "7")
try:
    LOOKBACK_DAYS = int(LOOKBACK_DAYS_ENV)
except ValueError:
    logging.warning(f"Invalid LOOKBACK_DAYS: {LOOKBACK_DAYS_ENV}. Defaulting to 7.")
    LOOKBACK_DAYS = 7

KEEP_MP3_ENV = os.getenv("KEEP_MP3", "false")
KEEP_MP3 = KEEP_MP3_ENV.lower() == "true"

# --- Import Folder Configuration ---
IMPORT_DIR_ENV = os.getenv("IMPORT_DIR", "")
IMPORT_DIR = Path(IMPORT_DIR_ENV) if IMPORT_DIR_ENV else None
SUPPORTED_IMPORT_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.opus']

IMPORT_CHECK_INTERVAL_SECONDS_ENV = os.getenv("IMPORT_CHECK_INTERVAL_SECONDS", "60")
try:
    IMPORT_CHECK_INTERVAL_SECONDS = int(IMPORT_CHECK_INTERVAL_SECONDS_ENV)
except ValueError:
    logging.warning(f"Invalid IMPORT_CHECK_INTERVAL_SECONDS: {IMPORT_CHECK_INTERVAL_SECONDS_ENV}. Defaulting to 60.")
    IMPORT_CHECK_INTERVAL_SECONDS = 60

# --- Output Directory Configuration ---
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/out")) # Allow overriding /out if needed, though typically fixed by Docker volume
TRANSCRIPTS_DIR = OUTPUT_DIR / "transcripts"
MP3_DIR = OUTPUT_DIR / "mp3" # For podcast downloads if KEEP_MP3 is true
STATE_FILE = OUTPUT_DIR / ".processed_episodes.log" # For podcast episodes

# --- Notification Configuration ---
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# --- Timezone ---
TZ = os.getenv("TZ", "UTC") # For logging purposes primarily

# --- PUID/PGID (Used by entrypoint, but good to have here if script needs them) ---
PUID = os.getenv("PUID", "99")
PGID = os.getenv("PGID", "100")