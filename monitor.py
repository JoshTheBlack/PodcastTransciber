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
# --- New Imports ---
from datetime import datetime, timedelta, timezone
# We need time module specifically to convert feedparser's time tuple
import time as time_module

# --- Configuration ---
PODCAST_FEEDS_ENV = os.getenv("PODCAST_FEEDS", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", 3600))
# --- New Configuration ---
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 7)) # How many days back to check for episodes
# --- End New Configuration ---
OUTPUT_DIR = Path("/out")
STATE_FILE = OUTPUT_DIR / ".processed_episodes.log" # Keep track of processed items

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    stream=sys.stdout) # Log to stdout for Docker logs

# Force python stdout/stderr streams to be unbuffered (redundant if set in Dockerfile/run command but safe)
os.environ['PYTHONUNBUFFERED'] = '1'


# --- Helper Functions ---

def sanitize_filename(filename):
    """Removes or replaces characters unsafe for filenames."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized[:200]

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
        with open(STATE_FILE, 'a') as f:
            f.write(f"{episode_id}\n")
    except Exception as e:
        logging.error(f"Error saving state for episode {episode_id} to {STATE_FILE}: {e}")

def get_episode_data(entry):
    """Extracts relevant data (ID, MP3 URL, suggested filename, pub date) from a feed entry."""
    episode_id = entry.get('id') or entry.get('guid') or entry.get('link')
    mp3_url = None
    filename_base = None
    published_date = None # <-- New: Initialize published_date

    if not episode_id:
        logging.warning(f"Could not determine unique ID for entry: {entry.get('title', 'No Title')}. Skipping.")
        return None, None, None, None

    # --- New: Extract and parse publication date ---
    try:
        if 'published_parsed' in entry and entry.published_parsed:
            # feedparser provides UTC time tuple
            # Convert struct_time (UTC) to datetime object (UTC)
            # Use time_module to avoid conflict with datetime.time
            utc_timestamp = time_module.mktime(entry.published_parsed)
            published_date = datetime.fromtimestamp(utc_timestamp, timezone.utc)
        elif 'published' in entry:
            # Fallback: Try parsing the string - this is less reliable due to format variations
            # feedparser might handle common RFC formats, let's try that first if parsed failed
            # For simplicity, we'll rely on published_parsed primarily.
            # More robust parsing (e.g., using dateutil.parser) could be added if needed.
            logging.warning(f"Episode ID {episode_id} has 'published' string but no 'published_parsed'. Date checking may be inaccurate.")
            # Attempt basic parsing if needed, but might fail:
            # from dateutil import parser
            # try: published_date = parser.parse(entry.published).astimezone(timezone.utc)
            # except: logging.warning("Could not parse 'published' string")
            pass # Keep published_date as None if parsing fails or isn't implemented robustly
    except Exception as e:
        logging.warning(f"Could not parse publication date for episode ID {episode_id}: {e}")
    # --- End Date Extraction ---


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
            logging.debug(f"No audio enclosure or suitable link found for episode ID {episode_id}. Skipping.")
            return episode_id, None, None, published_date # Return date even if no audio


    title = entry.get('title')
    if title:
        filename_base = sanitize_filename(title)
    else:
        url_path = Path(mp3_url)
        filename_base = sanitize_filename(url_path.stem if url_path.stem else f"episode_{episode_id}")

    return episode_id, mp3_url, filename_base, published_date


def download_episode(url, target_path):
    """Downloads a file from a URL to a target path."""
    try:
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

def format_timestamp(seconds: float) -> str:
    """Converts seconds to HH:MM:SS.mmm format."""
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)

    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000

    minutes = milliseconds // 60_000
    milliseconds %= 60_000

    secs = milliseconds // 1000
    milliseconds %= 1000

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

def transcribe_audio(model, audio_path, output_txt_path):
    """
    Transcribes an audio file using Whisper, formats with timestamps per segment,
    and saves to a text file. 
    """
    try:
        logging.info(f"Starting transcription for: {audio_path} using model '{WHISPER_MODEL}'")
        # Make Whisper verbose to see its progress in logs
        # You might want to set word_timestamps=True for more granularity if needed,
        # but segment-level is standard for this type of output.
        result = model.transcribe(str(audio_path), verbose=True) # verbose=None is less noisy

        logging.info(f"Transcription complete. Writing segments to: {output_txt_path}")

        # --- MODIFICATION START ---
        # Instead of using result["text"], iterate through segments
        with open(output_txt_path, 'w', encoding='utf-8') as f:
            segments = result.get("segments", [])
            if not segments:
                # If no segments, write the whole text if available (fallback)
                logging.warning(f"No segments found in transcription result for {audio_path}. Writing full text.")
                full_text = result.get("text", "").strip()
                if full_text:
                    f.write(full_text + "\n")
            else:
                for i, segment in enumerate(segments):
                    start_time = segment['start']
                    end_time = segment['end']
                    text = segment['text'].strip()

                    # Format timestamps
                    start_str = format_timestamp(start_time)
                    end_str = format_timestamp(end_time)

                    # Write the formatted line (similar to SRT/VTT)
                    # You can adjust this format if you prefer something else
                    f.write(f"[{start_str} --> {end_str}] {text}\n")
                    # Optionally add a segment number:
                    # f.write(f"{i+1}\n")
                    # f.write(f"{start_str} --> {end_str}\n")
                    # f.write(f"{text}\n\n")
        # --- MODIFICATION END ---

        logging.info(f"Formatted transcription saved successfully to {output_txt_path}")
        return True

    except Exception as e:
        logging.error(f"Failed to transcribe or format {audio_path}: {e}", exc_info=True)
        return False

# --- Main Execution ---

if __name__ == "__main__":
    logging.info("--- Podcast Monitor and Transcriber Starting ---")

    if not PODCAST_FEEDS_ENV:
        logging.error("PODCAST_FEEDS environment variable is not set or is empty. Exiting.")
        sys.exit(1)

    podcast_urls = [url.strip() for url in PODCAST_FEEDS_ENV.split(';') if url.strip()]
    if not podcast_urls:
        logging.error("No valid podcast feed URLs found in PODCAST_FEEDS environment variable after splitting. Exiting.")
        sys.exit(1)

    logging.info(f"Monitoring {len(podcast_urls)} feed(s): {', '.join(podcast_urls)}")
    logging.info(f"Using Whisper model: {WHISPER_MODEL}")
    logging.info(f"Output directory: {OUTPUT_DIR}")
    logging.info(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    logging.info(f"Lookback period: {LOOKBACK_DAYS} days") # Log lookback period

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        logging.info(f"Loading Whisper model '{WHISPER_MODEL}'...")
        whisper_model = whisper.load_model(WHISPER_MODEL)
        logging.info("Whisper model loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load Whisper model '{WHISPER_MODEL}': {e}. Exiting.")
        sys.exit(1)

    processed_episodes = load_processed_episodes()

    while True:
        logging.info("--- Starting feed check cycle ---")
        new_episodes_processed_this_cycle = 0

        # --- New: Calculate cutoff date for this cycle ---
        # Use UTC for comparison
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        logging.info(f"Processing episodes published on or after: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        # --- End New ---

        for feed_url in podcast_urls:
            logging.info(f"Checking feed: {feed_url}")
            try:
                feed = feedparser.parse(feed_url)

                if feed.bozo:
                    logging.warning(f"Feed {feed_url} may be ill-formed. Bozo reason: {feed.bozo_exception}")

                if feed.status != 200 and feed.status not in [301, 302, 307, 308]: # Include redirects
                     logging.warning(f"Feed {feed_url} returned status code: {feed.status}. Skipping.")
                     continue

                # Process entries (consider oldest first within the lookback if needed, but chronological is fine)
                for entry in feed.entries: # feed.entries are usually newest first
                    episode_id, mp3_url, filename_base, published_date = get_episode_data(entry)

                    # Skip if essential data missing
                    if not episode_id or not mp3_url or not filename_base:
                        continue

                    # --- New: Check Publication Date ---
                    if published_date:
                        # Ensure published_date is timezone-aware for correct comparison
                        if published_date.tzinfo is None:
                             # If feedparser didn't provide tzinfo, assume UTC as per standard practice
                             published_date = published_date.replace(tzinfo=timezone.utc)

                        if published_date < cutoff_date:
                            logging.debug(f"Episode ID {episode_id} published at {published_date} is older than cutoff {cutoff_date}. Skipping.")
                            continue # Skip episodes older than the lookback period
                    else:
                        # If we couldn't parse a date, we can't apply the time filter.
                        # Decide whether to skip or process. Skipping is safer for the requirement.
                        logging.warning(f"Episode ID {episode_id} has no parsable publication date. Skipping due to lookback constraint.")
                        continue
                    # --- End Date Check ---


                    # --- Existing Check: Skip if already processed ---
                    if episode_id in processed_episodes:
                        logging.debug(f"Episode ID {episode_id} already processed. Skipping.")
                        continue
                    # --- End Processed Check ---

                    # --- New Episode within lookback period ---
                    logging.info(f"New episode found in {feed_url} within lookback period: '{entry.get('title', 'No Title')}' (ID: {episode_id}, Pub: {published_date})")
                    new_episodes_processed_this_cycle += 1

                    mp3_filename = f"{filename_base}.mp3"
                    txt_filename = f"{filename_base}.txt"
                    temp_mp3_path = OUTPUT_DIR / f"_temp_{mp3_filename}"
                    final_mp3_path = OUTPUT_DIR / mp3_filename
                    output_txt_path = OUTPUT_DIR / txt_filename

                    if final_mp3_path.exists() or output_txt_path.exists():
                        logging.warning(f"Output file(s) for episode ID {episode_id} already exist in {OUTPUT_DIR}. Marking as processed and skipping.")
                        if episode_id not in processed_episodes:
                           save_processed_episode(episode_id)
                           processed_episodes.add(episode_id)
                        continue

                    if not download_episode(mp3_url, temp_mp3_path):
                        logging.error(f"Download failed for episode {episode_id}. Skipping.")
                        continue

                    if not transcribe_audio(whisper_model, temp_mp3_path, output_txt_path):
                        logging.error(f"Transcription failed for episode {episode_id}. Cleaning up.")
                        try: os.remove(temp_mp3_path)
                        except OSError as e: logging.error(f"Error removing temp file {temp_mp3_path}: {e}")
                        continue

                    try:
                        shutil.move(str(temp_mp3_path), str(final_mp3_path))
                        logging.info(f"Moved completed MP3 to {final_mp3_path}")
                    except Exception as e:
                        logging.error(f"Failed to move {temp_mp3_path} to {final_mp3_path}: {e}")

                    save_processed_episode(episode_id)
                    processed_episodes.add(episode_id)
                    logging.info(f"Successfully processed and saved episode ID: {episode_id}")

            except Exception as e:
                logging.error(f"Failed to process feed {feed_url}: {e}", exc_info=True)

        logging.info(f"--- Feed check cycle complete. Processed {new_episodes_processed_this_cycle} new episodes this cycle. ---")
        logging.info(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        # Use time_module to avoid conflict
        time_module.sleep(CHECK_INTERVAL_SECONDS)