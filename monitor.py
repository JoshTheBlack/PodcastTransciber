import os
import feedparser
import requests
import time
# Note: 'whisper' import is removed
import logging
import shutil
import sys
from pathlib import Path
import re
from datetime import datetime, timedelta, timezone
import time as time_module # Use alias to avoid name conflict

# --- NEW: faster-whisper import ---
from faster_whisper import WhisperModel
# --- End Import ---


# --- Configuration ---
PODCAST_FEEDS_ENV = os.getenv("PODCAST_FEEDS", "")
# --- Faster-Whisper Specific Config ---
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
DEVICE = os.getenv("DEVICE", "cpu")
# See faster-whisper docs for optimal compute_type per device/model
# 'default' is usually good to start. Others: int8, float16, int8_float16 etc.
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "default")
# --- End Faster-Whisper Config ---
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", 3600))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 7))
DEBUG_LOGGING = os.getenv("DEBUG_LOGGING", "false").lower() == "true"

# --- NEW: Environment variables for new features ---
# KEEP_MP3: If 'true', MP3s are kept. Otherwise (unset or 'false'), they are deleted.
KEEP_MP3 = os.getenv("KEEP_MP3", "false").lower() == "true"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
# --- End New Environment variables ---

# --- Output Directory Configuration ---
OUTPUT_DIR = Path("/out")
TRANSCRIPTS_DIR = OUTPUT_DIR / "transcripts"
MP3_DIR = OUTPUT_DIR / "mp3"
STATE_FILE = OUTPUT_DIR / ".processed_episodes.log"

# --- Setup Logging ---
log_level = logging.DEBUG if DEBUG_LOGGING else logging.INFO
logging.basicConfig(level=log_level,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    stream=sys.stdout)
logging.info(f"Debug logging enabled: {DEBUG_LOGGING}")

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
    processed = set()
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                for line in f: processed.add(line.strip())
            logging.info(f"Loaded {len(processed)} processed episode IDs from {STATE_FILE}")
        except Exception as e: logging.error(f"Error loading state file {STATE_FILE}: {e}")
    else: logging.info(f"State file {STATE_FILE} not found. Starting fresh.")
    return processed

def save_processed_episode(episode_id):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, 'a') as f: f.write(f"{episode_id}\n")
    except Exception as e: logging.error(f"Error saving state for episode {episode_id} to {STATE_FILE}: {e}")

def get_episode_data(entry):
    episode_id = entry.get('id') or entry.get('guid') or entry.get('link')
    mp3_url = None; filename_base = None; published_date = None
    if not episode_id: logging.warning(f"Could not determine unique ID for entry: {entry.get('title', 'No Title')}. Skipping."); return None, None, None, None
    try:
        if 'published_parsed' in entry and entry.published_parsed:
            utc_timestamp = time_module.mktime(entry.published_parsed); published_date = datetime.fromtimestamp(utc_timestamp, timezone.utc)
        elif 'published' in entry: logging.debug(f"Episode ID {episode_id} using 'published' string.")
    except Exception as e: logging.warning(f"Could not parse publication date for episode ID {episode_id}: {e}")
    if 'enclosures' in entry:
        for enclosure in entry.enclosures:
            if enclosure.get('type', '').startswith('audio'): mp3_url = enclosure.href; break
    if not mp3_url:
        link = entry.get('link')
        if link and any(link.lower().endswith(ext) for ext in ['.mp3', '.m4a', '.wav', '.ogg']): mp3_url = link
        else: logging.debug(f"No audio enclosure or suitable link found for episode ID {episode_id}. Skipping."); return episode_id, None, None, published_date
    title = entry.get('title')
    if title: filename_base = sanitize_filename(title)
    else: url_path = Path(mp3_url); filename_base = sanitize_filename(url_path.stem if url_path.stem else f"episode_{episode_id}")
    return episode_id, mp3_url, filename_base, published_date

def download_episode(url, target_path):
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(f"Downloading: {url} to {target_path}")
        response = requests.get(url, stream=True); response.raise_for_status()
        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        logging.info(f"Download complete: {target_path}")
        return True
    except requests.exceptions.RequestException as e: logging.error(f"Failed to download {url}: {e}")
    except Exception as e: logging.error(f"An unexpected error occurred during download of {url}: {e}")
    if target_path.exists():
        try: os.remove(target_path)
        except OSError as oe: logging.error(f"Error removing incomplete file {target_path}: {oe}")
    return False

def transcribe_audio(model: WhisperModel, audio_path: Path, output_txt_path: Path):
    """
    Transcribes audio using faster-whisper.
    Saves formatted transcript with timestamps.
    """
    try:
        output_txt_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(f"Starting transcription for: {audio_path}")
        segments, info = model.transcribe(str(audio_path), beam_size=5)
        logging.info(f"Detected language '{info.language}' with probability {info.language_probability:.2f}")
        logging.info(f"Audio duration processed: {format_timestamp(info.duration)}")
        logging.info(f"Writing transcription segments to: {output_txt_path}")
        segment_count = 0
        with open(output_txt_path, 'w', encoding='utf-8') as f:
            for segment in segments:
                start_str = format_timestamp(segment.start)
                end_str = format_timestamp(segment.end)
                f.write(f"[{start_str} --> {end_str}] {segment.text}\n")
                segment_count += 1
                if DEBUG_LOGGING and segment_count % 20 == 0:
                     logging.debug(f"Processed segment {segment_count} ending at {end_str}")
        logging.info(f"Formatted transcription with {segment_count} segments saved to {output_txt_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to transcribe or format {audio_path}: {e}", exc_info=True)
        return False

def send_to_discord(webhook_url: str, file_path: Path, episode_title: str):
    """
    Attempts to send the transcript file to a Discord webhook.
    """
    if not webhook_url:
        return
    if not file_path.exists():
        logging.error(f"Discord: Transcript file not found at {file_path}, cannot send.")
        return
    try:
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > 7.5:
            logging.warning(f"Discord: Transcript file {file_path.name} is ~{file_size_mb:.2f}MB, sending message instead of file.")
            message_content = f"Transcription complete for: **{episode_title}**\nTranscript file `{file_path.name}` was too large to upload directly ({file_size_mb:.2f}MB)."
            payload = {"content": message_content}
            response = requests.post(webhook_url, json=payload)
        else:
            with open(file_path, 'rb') as f:
                payload = {"content": f"Transcription complete for: **{episode_title}**"}
                files = {'file': (file_path.name, f, 'text/plain')}
                response = requests.post(webhook_url, data=payload, files=files)
        response.raise_for_status()
        logging.info(f"Successfully sent transcript {file_path.name} to Discord.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send transcript {file_path.name} to Discord: {e}")
        if e.response is not None:
            logging.error(f"Discord response: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while sending to Discord: {e}", exc_info=True)

# --- Main Execution ---
if __name__ == "__main__":
    logging.info("--- Podcast Monitor and Transcriber Starting ---")
    logging.info(f"Current Time (UTC): {datetime.now(timezone.utc)}")

    if not PODCAST_FEEDS_ENV: logging.error("PODCAST_FEEDS env var not set. Exiting."); sys.exit(1)
    podcast_urls = [url.strip() for url in PODCAST_FEEDS_ENV.split(';') if url.strip()]
    if not podcast_urls: logging.error("No valid podcast URLs found. Exiting."); sys.exit(1)

    logging.info(f"Monitoring {len(podcast_urls)} feed(s): {', '.join(podcast_urls)}")
    logging.info(f"Using faster-whisper model: {WHISPER_MODEL}")
    logging.info(f"Using device: {DEVICE}, compute_type: {COMPUTE_TYPE}")
    logging.info(f"Base Output directory: {OUTPUT_DIR}")
    logging.info(f"Transcript directory: {TRANSCRIPTS_DIR}")
    logging.info(f"MP3 directory: {MP3_DIR}")
    logging.info(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    logging.info(f"Lookback period: {LOOKBACK_DAYS} days")
    # --- NEW: Log new feature settings ---
    logging.info(f"Keep MP3 after transcoding: {KEEP_MP3}") # Updated log message
    if DISCORD_WEBHOOK_URL:
        logging.info(f"Discord webhook URL is set. Transcripts will be sent.")
    else:
        logging.info(f"Discord webhook URL is NOT set. Skipping Discord notifications.")
    # --- End Log new feature settings ---

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    MP3_DIR.mkdir(parents=True, exist_ok=True) # Ensure MP3_DIR is created even if MP3s are deleted
    logging.info("Output directories ensured.")

    try:
        logging.info(f"Loading faster-whisper model '{WHISPER_MODEL}' (device={DEVICE}, compute_type={COMPUTE_TYPE})...")
        whisper_model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE_TYPE)
        logging.info("Faster-whisper model loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load faster-whisper model: {e}. Exiting.", exc_info=True)
        sys.exit(1)

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
                if feed.bozo: logging.warning(f"Feed {feed_url} may be ill-formed. Reason: {feed.bozo_exception}")
                if feed.status != 200 and feed.status not in [301, 302, 307, 308]:
                     logging.warning(f"Feed {feed_url} returned status code: {feed.status}. Skipping."); continue

                for entry in feed.entries:
                    episode_id, mp3_url, filename_base, published_date = get_episode_data(entry)
                    original_episode_title = entry.get('title', 'No Title')

                    if not episode_id or not mp3_url or not filename_base: continue
                    if published_date:
                        if published_date.tzinfo is None: published_date = published_date.replace(tzinfo=timezone.utc)
                        if published_date < cutoff_date: logging.debug(f"Episode ID {episode_id} older than {LOOKBACK_DAYS} days. Skipping."); continue
                    else: logging.warning(f"Episode ID {episode_id} ('{original_episode_title}') has no parsable publication date. Skipping."); continue
                    if episode_id in processed_episodes: logging.debug(f"Episode ID {episode_id} ('{original_episode_title}') already processed. Skipping."); continue

                    logging.info(f"New episode found: '{original_episode_title}' (ID: {episode_id})")
                    new_episodes_processed_this_cycle += 1
                    mp3_filename = f"{filename_base}.mp3"; txt_filename = f"{filename_base}.txt"
                    # Download to MP3_DIR directly as _temp_ only if we might delete it.
                    # If keeping, we can download directly to final name if not already existing.
                    # However, using a _temp_ name is safer for incomplete downloads.
                    temp_mp3_path = MP3_DIR / f"_temp_{mp3_filename}"
                    final_mp3_path = MP3_DIR / mp3_filename
                    output_txt_path = TRANSCRIPTS_DIR / txt_filename

                    # Check if final output already exists
                    # If keeping MP3s, and final MP3 exists, or if transcript exists, skip.
                    if (KEEP_MP3 and final_mp3_path.exists()) or output_txt_path.exists():
                        logging.warning(f"Output file(s) for episode ID {episode_id} ('{original_episode_title}') already exist (MP3 kept: {KEEP_MP3}, Transcript: {output_txt_path.exists()}). Marking as processed and skipping.")
                        if episode_id not in processed_episodes: save_processed_episode(episode_id); processed_episodes.add(episode_id)
                        continue
                    # If deleting MP3s, only transcript existence matters for skipping.
                    elif (not KEEP_MP3 and output_txt_path.exists()):
                        logging.warning(f"Transcript for episode ID {episode_id} ('{original_episode_title}') already exists and MP3s are set to be deleted. Marking as processed and skipping.")
                        if episode_id not in processed_episodes: save_processed_episode(episode_id); processed_episodes.add(episode_id)
                        continue


                    if not download_episode(mp3_url, temp_mp3_path): continue

                    transcription_successful = transcribe_audio(whisper_model, temp_mp3_path, output_txt_path)

                    if not transcription_successful:
                        logging.error(f"Transcription failed for episode ID {episode_id} ('{original_episode_title}'). Cleaning up temporary MP3.")
                        try:
                            if temp_mp3_path.exists(): os.remove(temp_mp3_path)
                        except OSError as e: logging.error(f"Error removing temp file {temp_mp3_path} after failed transcription: {e}")
                        continue

                    # --- Handle MP3 file based on KEEP_MP3 ---
                    if KEEP_MP3:
                        try:
                            shutil.move(str(temp_mp3_path), str(final_mp3_path))
                            logging.info(f"MP3 file kept and moved to {final_mp3_path}")
                        except Exception as e:
                            logging.error(f"Failed to move {temp_mp3_path} to {final_mp3_path}: {e}")
                            # If move fails, temp_mp3_path might still exist.
                            # Consider if this should prevent marking as processed. For now, we proceed.
                    else: # Delete MP3 (KEEP_MP3 is false)
                        try:
                            logging.info(f"Deleting MP3 file as per configuration: {temp_mp3_path}")
                            os.remove(temp_mp3_path)
                            logging.info(f"Successfully deleted MP3: {temp_mp3_path}")
                        except OSError as e:
                            logging.error(f"Failed to delete MP3 file {temp_mp3_path}: {e}")

                    if transcription_successful and DISCORD_WEBHOOK_URL:
                        send_to_discord(DISCORD_WEBHOOK_URL, output_txt_path, original_episode_title)

                    save_processed_episode(episode_id)
                    processed_episodes.add(episode_id)
                    logging.info(f"Successfully processed and saved state for episode ID: {episode_id} ('{original_episode_title}')")

            except Exception as e: logging.error(f"Major error processing feed {feed_url}: {e}", exc_info=True)

        logging.info(f"--- Feed check cycle complete. Processed {new_episodes_processed_this_cycle} new episodes this cycle. ---")
        logging.info(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        time_module.sleep(CHECK_INTERVAL_SECONDS)