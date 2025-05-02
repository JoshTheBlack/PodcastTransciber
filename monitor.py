import os
import feedparser
import requests
import time
import whisper
import logging
import shutil
import sys
from pathlib import Path
import re
from datetime import datetime, timedelta, timezone
import time as time_module # Use alias to avoid name conflict

# --- Configuration ---
PODCAST_FEEDS_ENV = os.getenv("PODCAST_FEEDS", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", 3600))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 7))
# Set DEBUG_LOGGING=true in environment for verbose Whisper output and DEBUG level logs
DEBUG_LOGGING = os.getenv("DEBUG_LOGGING", "false").lower() == "true"

# --- Output Directory Configuration ---
OUTPUT_DIR = Path("/out")
TRANSCRIPTS_DIR = OUTPUT_DIR / "transcripts"
MP3_DIR = OUTPUT_DIR / "mp3"
STATE_FILE = OUTPUT_DIR / ".processed_episodes.log"

# --- Setup Logging ---
# Set logging level based on DEBUG_LOGGING flag
log_level = logging.DEBUG if DEBUG_LOGGING else logging.INFO
logging.basicConfig(level=log_level,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    stream=sys.stdout)
logging.info(f"Debug logging enabled: {DEBUG_LOGGING}") # Log whether debug is on/off
# --- End Logging Setup ---

# Force python stdout/stderr streams to be unbuffered (good practice in Docker)
os.environ['PYTHONUNBUFFERED'] = '1'


# --- Helper Functions ---

def sanitize_filename(filename):
    """Removes or replaces characters unsafe for filenames."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized[:200]

def format_timestamp(seconds: float) -> str:
    """Converts seconds to HH:MM:SS.mmm format."""
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)
    hours = milliseconds // 3_600_000; milliseconds %= 3_600_000
    minutes = milliseconds // 60_000; milliseconds %= 60_000
    secs = milliseconds // 1000; milliseconds %= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

def load_processed_episodes():
    """Loads the set of processed episode IDs from the state file."""
    processed = set()
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                for line in f:
                    processed.add(line.strip())
            logging.info(f"Loaded {len(processed)} processed episode IDs from {STATE_FILE}")
        except Exception as e:
            logging.error(f"Error loading state file {STATE_FILE}: {e}")
    else:
        logging.info(f"State file {STATE_FILE} not found. Starting fresh.")
    return processed

def save_processed_episode(episode_id):
    """Appends a processed episode ID to the state file."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, 'a') as f:
            f.write(f"{episode_id}\n")
    except Exception as e:
        logging.error(f"Error saving state for episode {episode_id} to {STATE_FILE}: {e}")

def get_episode_data(entry):
    """Extracts relevant data (ID, MP3 URL, suggested filename, pub date) from a feed entry."""
    # ... (rest of the function remains the same - using logging.warning for actual issues) ...
    episode_id = entry.get('id') or entry.get('guid') or entry.get('link')
    mp3_url = None
    filename_base = None
    published_date = None

    if not episode_id:
        logging.warning(f"Could not determine unique ID for entry: {entry.get('title', 'No Title')}. Skipping.")
        return None, None, None, None

    try:
        if 'published_parsed' in entry and entry.published_parsed:
            utc_timestamp = time_module.mktime(entry.published_parsed)
            published_date = datetime.fromtimestamp(utc_timestamp, timezone.utc)
        elif 'published' in entry:
            logging.debug(f"Episode ID {episode_id} using 'published' string. Date parsing may be less reliable.") # Changed to DEBUG
            pass
    except Exception as e:
        logging.warning(f"Could not parse publication date for episode ID {episode_id}: {e}")

    if 'enclosures' in entry:
        for enclosure in entry.enclosures:
            if enclosure.get('type', '').startswith('audio'):
                mp3_url = enclosure.href
                break

    if not mp3_url:
        link = entry.get('link')
        if link and any(link.lower().endswith(ext) for ext in ['.mp3', '.m4a', '.wav', '.ogg']):
             mp3_url = link
        else:
            # Changed to DEBUG as this is common for non-episode entries
            logging.debug(f"No audio enclosure or suitable link found for episode ID {episode_id}. Skipping.")
            return episode_id, None, None, published_date

    title = entry.get('title')
    if title:
        filename_base = sanitize_filename(title)
    else:
        url_path = Path(mp3_url)
        filename_base = sanitize_filename(url_path.stem if url_path.stem else f"episode_{episode_id}")

    return episode_id, mp3_url, filename_base, published_date


def download_episode(url, target_path):
    """Downloads a file from a URL to a target path."""
    # ... (function remains largely the same, logging start/completion/errors) ...
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(f"Downloading: {url} to {target_path}")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.info(f"Download complete: {target_path}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download {url}: {e}")
        if target_path.exists():
            try: os.remove(target_path)
            except OSError as oe: logging.error(f"Error removing incomplete file {target_path}: {oe}")
        return False
    except Exception as e:
        logging.error(f"An unexpected error occurred during download of {url}: {e}")
        if target_path.exists():
            try: os.remove(target_path)
            except OSError as oe: logging.error(f"Error removing incomplete file {target_path}: {oe}")
        return False


def transcribe_audio(model, audio_path, output_txt_path):
    """
    Transcribes audio using Whisper. Verbosity depends on DEBUG_LOGGING.
    Saves formatted transcript with timestamps.
    """
    try:
        output_txt_path.parent.mkdir(parents=True, exist_ok=True)

        # --- Control Whisper verbosity based on debug flag ---
        # Use verbose=True for debug, verbose=None for standard (shows some progress)
        whisper_verbosity = True if DEBUG_LOGGING else None
        logging.info(f"Starting transcription for: {audio_path} (Whisper verbose={whisper_verbosity})")
        # --- End Verbosity Control ---

        result = model.transcribe(str(audio_path), verbose=whisper_verbosity)

        logging.info(f"Transcription finished by Whisper. Writing segments to: {output_txt_path}")

        with open(output_txt_path, 'w', encoding='utf-8') as f:
            segments = result.get("segments", [])
            if not segments:
                logging.warning(f"No segments found in transcription result for {audio_path}. Writing full text.")
                full_text = result.get("text", "").strip()
                if full_text: f.write(full_text + "\n")
            else:
                for i, segment in enumerate(segments):
                    start_time = segment['start']; end_time = segment['end']
                    text = segment['text'].strip()
                    start_str = format_timestamp(start_time); end_str = format_timestamp(end_time)
                    f.write(f"[{start_str} --> {end_str}] {text}\n")

        logging.info(f"Formatted transcription saved successfully to {output_txt_path}")
        return True

    except Exception as e:
        logging.error(f"Failed to transcribe or format {audio_path}: {e}", exc_info=True)
        return False

# --- Main Execution ---

if __name__ == "__main__":
    logging.info("--- Podcast Monitor and Transcriber Starting ---")
    logging.info(f"Current Time (UTC): {datetime.now(timezone.utc)}")

    # ... (Feed URL checks remain the same) ...
    if not PODCAST_FEEDS_ENV: logging.error("PODCAST_FEEDS env var not set. Exiting."); sys.exit(1)
    podcast_urls = [url.strip() for url in PODCAST_FEEDS_ENV.split(';') if url.strip()]
    if not podcast_urls: logging.error("No valid podcast URLs found. Exiting."); sys.exit(1)

    logging.info(f"Monitoring {len(podcast_urls)} feed(s): {', '.join(podcast_urls)}")
    logging.info(f"Using Whisper model: {WHISPER_MODEL}")
    logging.info(f"Base Output directory: {OUTPUT_DIR}")
    logging.info(f"Transcript directory: {TRANSCRIPTS_DIR}")
    logging.info(f"MP3 directory: {MP3_DIR}")
    logging.info(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    logging.info(f"Lookback period: {LOOKBACK_DAYS} days")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    MP3_DIR.mkdir(parents=True, exist_ok=True)
    logging.info("Output directories ensured.")

    try:
        logging.info(f"Loading Whisper model '{WHISPER_MODEL}'...")
        whisper_model = whisper.load_model(WHISPER_MODEL)
        logging.info("Whisper model loaded successfully.")
    except Exception as e: logging.error(f"Failed to load Whisper model: {e}. Exiting."); sys.exit(1)

    processed_episodes = load_processed_episodes()

    while True:
        logging.info("--- Starting feed check cycle ---")
        new_episodes_processed_this_cycle = 0
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        logging.info(f"Processing episodes published on or after: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        for feed_url in podcast_urls:
            logging.info(f"Checking feed: {feed_url}")
            try:
                feed = feedparser.parse(feed_url)
                # ... (Feed status checks remain the same) ...
                if feed.bozo: logging.warning(f"Feed {feed_url} may be ill-formed. Reason: {feed.bozo_exception}")
                if feed.status != 200 and feed.status not in [301, 302, 307, 308]:
                     logging.warning(f"Feed {feed_url} returned status code: {feed.status}. Skipping."); continue

                for entry in feed.entries:
                    episode_id, mp3_url, filename_base, published_date = get_episode_data(entry)

                    if not episode_id or not mp3_url or not filename_base: continue # Skips handled in get_episode_data logs

                    # --- Date Check ---
                    if published_date:
                        if published_date.tzinfo is None: published_date = published_date.replace(tzinfo=timezone.utc)
                        if published_date < cutoff_date:
                            # Changed to DEBUG level
                            logging.debug(f"Episode ID {episode_id} ({published_date}) older than cutoff {cutoff_date}. Skipping.")
                            continue
                    else:
                        logging.warning(f"Episode ID {episode_id} has no parsable publication date. Skipping due to lookback constraint.")
                        continue
                    # --- End Date Check ---

                    # --- Processed Check ---
                    if episode_id in processed_episodes:
                        # Changed to DEBUG level
                        logging.debug(f"Episode ID {episode_id} already processed. Skipping.")
                        continue
                    # --- End Processed Check ---

                    logging.info(f"New episode found: '{entry.get('title', 'No Title')}' (ID: {episode_id})")
                    new_episodes_processed_this_cycle += 1

                    mp3_filename = f"{filename_base}.mp3"
                    txt_filename = f"{filename_base}.txt"
                    temp_mp3_path = MP3_DIR / f"_temp_{mp3_filename}"
                    final_mp3_path = MP3_DIR / mp3_filename
                    output_txt_path = TRANSCRIPTS_DIR / txt_filename

                    if final_mp3_path.exists() or output_txt_path.exists():
                        logging.warning(f"Output file(s) for episode ID {episode_id} already exist. Marking processed.")
                        if episode_id not in processed_episodes:
                           save_processed_episode(episode_id)
                           processed_episodes.add(episode_id)
                        continue

                    if not download_episode(mp3_url, temp_mp3_path): continue
                    if not transcribe_audio(whisper_model, temp_mp3_path, output_txt_path):
                        logging.error(f"Transcription failed for {episode_id}. Cleaning up temp file.")
                        try: os.remove(temp_mp3_path)
                        except OSError as e: logging.error(f"Error removing temp file {temp_mp3_path}: {e}")
                        continue

                    try:
                        shutil.move(str(temp_mp3_path), str(final_mp3_path))
                        logging.info(f"Renamed/Moved completed MP3 to {final_mp3_path}")
                    except Exception as e: logging.error(f"Failed to move {temp_mp3_path} to {final_mp3_path}: {e}")

                    save_processed_episode(episode_id)
                    processed_episodes.add(episode_id)
                    logging.info(f"Successfully processed and saved episode ID: {episode_id}")

            except Exception as e: logging.error(f"Failed to process feed {feed_url}: {e}", exc_info=True)

        logging.info(f"--- Feed check cycle complete. Processed {new_episodes_processed_this_cycle} new episodes this cycle. ---")
        logging.info(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        time_module.sleep(CHECK_INTERVAL_SECONDS)