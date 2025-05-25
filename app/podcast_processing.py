# app/podcast_processing.py
import logging
import feedparser
import requests
import time as time_module # Use alias
from datetime import datetime, timezone
from pathlib import Path

import config # Import from our config module
import utils # Import from our utils module

logger = logging.getLogger(__name__)

def load_processed_episodes():
    processed = set()
    if config.STATE_FILE.exists():
        try:
            with open(config.STATE_FILE, 'r') as f:
                for line in f:
                    processed.add(line.strip())
            logger.info(f"Loaded {len(processed)} processed episode GUIDs from {config.STATE_FILE}")
        except Exception as e:
            logger.error(f"Error loading state file {config.STATE_FILE}: {e}")
    else:
        logger.info(f"State file {config.STATE_FILE} not found for podcast episodes. Starting fresh.")
    return processed

def save_processed_episode(episode_id):
    try:
        config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(config.STATE_FILE, 'a') as f:
            f.write(f"{episode_id}\n")
    except Exception as e:
        logger.error(f"Error saving state for episode {episode_id} to {config.STATE_FILE}: {e}")

def get_episode_data(entry):
    # Using GUID as primary identifier
    episode_id = entry.get('id') or entry.get('guid') or entry.get('link')
    mp3_url = None
    published_date = None
    
    title = entry.get('title', f"episode_{episode_id if episode_id else 'unknown'}")
    filename_base = utils.sanitize_filename(title)

    if not episode_id:
        logger.warning(f"Could not determine unique ID for entry: {title}. Skipping.")
        return None, None, None, None, None

    try:
        if 'published_parsed' in entry and entry.published_parsed:
            utc_timestamp = time_module.mktime(entry.published_parsed)
            published_date = datetime.fromtimestamp(utc_timestamp, timezone.utc)
        elif 'published' in entry:
            # Attempt to parse 'published' string
            try:
                published_date = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %z").astimezone(timezone.utc)
            except ValueError:
                try:
                    published_date = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.debug(f"Could not parse 'published' string: {entry.published} for episode {filename_base} (ID: {episode_id})")
    except Exception as e:
        logger.warning(f"Error parsing publication date for episode {filename_base} (ID: {episode_id}): {e}")

    if 'enclosures' in entry:
        for enclosure in entry.enclosures:
            if enclosure.get('type', '').startswith('audio'):
                mp3_url = enclosure.href
                break
    if not mp3_url:
        link = entry.get('link')
        if link and any(link.lower().endswith(ext) for ext in config.SUPPORTED_IMPORT_EXTENSIONS):
            mp3_url = link
        else:
            logger.debug(f"No audio enclosure or suitable link for episode {filename_base} (ID: {episode_id}). Skipping.")
            return episode_id, title, None, None, published_date
            
    return episode_id, title, mp3_url, filename_base, published_date

def download_episode(url, target_path: Path):
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading: {url} to {target_path}")
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Download complete: {target_path}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download {url}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during download of {url}: {e}")
    
    if target_path.exists(): # Cleanup incomplete download
        try:
            target_path.unlink()
        except OSError as oe:
            logger.error(f"Error removing incomplete file {target_path}: {oe}")
    return False