# app/main.py
import logging
import sys
import time as time_module
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil # For moving podcast MP3s if kept
import os # For removing podcast MP3s

# Import from our new local modules
import config
import logger_setup
import utils
import podcast_processing
import transcription
import import_handler
import notifications

# Setup logging as the first step
logger_setup.setup_logging()
logger = logging.getLogger(__name__) # Get logger for this main module

def ensure_directories():
    """Creates necessary output and import directories if they don't exist."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    if config.KEEP_MP3:
        config.MP3_DIR.mkdir(parents=True, exist_ok=True)
    if config.IMPORT_DIR:
        config.IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Output and import directories ensured.")

def main_loop(transcription_model_obj, processed_episode_guids_set):
    """Main processing loop."""
    while True:
        # 1. Process Import Folder (Priority at the start of a full cycle)
        if config.IMPORT_DIR and transcription_model_obj:
            logger.info("--- Checking import folder (start of main cycle) ---")
            import_handler.process_import_folder(
                transcription_model_obj,
                transcription.transcribe_audio, # Pass the main transcription function
                notifications.send_to_discord   # Pass the notification function
            )
        
        # 2. Process Podcast Feeds
        if config.podcast_urls:
            logger.info("--- Starting podcast feed check cycle ---")
            new_episodes_processed_this_cycle = 0
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=config.LOOKBACK_DAYS)
            logger.info(f"Processing podcast episodes published on or after: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")

            for feed_url in config.podcast_urls:
                logger.info(f"Checking feed: {feed_url}")
                try:
                    feed = podcast_processing.feedparser.parse(feed_url) # feedparser is used within podcast_processing now
                    if feed.bozo:
                        logger.warning(f"Feed {feed_url} may be ill-formed. Reason: {feed.bozo_exception}")
                    if feed.status not in [200, 301, 302, 304, 307, 308]: 
                         logger.warning(f"Feed {feed_url} returned status code: {feed.status}. Skipping for this cycle.")
                         continue

                    for entry in feed.entries:
                        episode_guid, episode_title, mp3_url, filename_base, published_date = \
                            podcast_processing.get_episode_data(entry)

                        if not episode_guid or not mp3_url or not filename_base:
                            continue # Issues already logged by get_episode_data

                        if published_date:
                            if published_date.tzinfo is None:
                                published_date = published_date.replace(tzinfo=timezone.utc)
                            if published_date < cutoff_date: 
                                logger.debug(f"Episode '{episode_title}' (GUID: {episode_guid}) published {published_date} is older. Skipping.")
                                continue
                        elif not config.IMPORT_DIR: # Only skip if not also relying on import dir as a primary function
                            logger.warning(f"Episode '{episode_title}' (GUID: {episode_guid}) has no parsable publication date. Skipping as podcast-only mode.")
                            # If IMPORT_DIR is set, we might process undated items if they appear, but typically GUIDs prevent reprocessing
                            # For strict podcast mode, uncomment below to skip if no date.
                            # continue 
                        
                        if episode_guid in processed_episode_guids_set:
                            logger.debug(f"Episode '{episode_title}' (GUID: {episode_guid}) already processed. Skipping.")
                            continue

                        logger.info(f"New podcast episode found: '{episode_title}' (GUID: {episode_guid})")
                        
                        txt_filename = f"{filename_base}.txt"
                        final_output_txt_path = config.TRANSCRIPTS_DIR / txt_filename

                        if final_output_txt_path.exists():
                            logger.warning(f"Transcript for podcast episode '{episode_title}' already exists: {final_output_txt_path}. Marking as processed.")
                            if episode_guid not in processed_episode_guids_set:
                                podcast_processing.save_processed_episode(episode_guid)
                                processed_episode_guids_set.add(episode_guid)
                            continue

                        # Determine temporary MP3 path
                        mp3_filename = f"{filename_base}.mp3"
                        temp_mp3_dir_base = config.MP3_DIR if config.KEEP_MP3 else config.OUTPUT_DIR 
                        temp_mp3_path = temp_mp3_dir_base / f"_temp_{mp3_filename}"
                        temp_mp3_path.parent.mkdir(parents=True, exist_ok=True) # Ensure dir for temp_mp3

                        if not podcast_processing.download_episode(mp3_url, temp_mp3_path):
                            logger.warning(f"Download failed for '{episode_title}'. Will retry next cycle.")
                            continue 
                        
                        new_episodes_processed_this_cycle += 1
                        config.TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
                        
                        transcription_successful = transcription.transcribe_audio(
                            transcription_model_obj,
                            temp_mp3_path,
                            final_output_txt_path
                        )

                        if not transcription_successful:
                            logger.error(f"Transcription failed for podcast episode '{episode_title}' (GUID: {episode_guid}).")
                            # Temp MP3 cleanup handled by download_episode on failure or below if KEEP_MP3 is false
                            if temp_mp3_path.exists() and not config.KEEP_MP3: # ensure cleanup if transcribe failed and we're not keeping
                                try: temp_mp3_path.unlink()
                                except OSError as e: logger.error(f"Error removing temp MP3 {temp_mp3_path} after failed transcription: {e}")
                            continue 

                        # Handle MP3 after successful transcription
                        final_mp3_path = config.MP3_DIR / mp3_filename
                        if config.KEEP_MP3:
                            try:
                                if temp_mp3_path.exists():
                                    shutil.move(str(temp_mp3_path), str(final_mp3_path))
                                    logger.info(f"Podcast MP3 file kept and moved to {final_mp3_path}")
                            except Exception as e:
                                logger.error(f"Failed to move podcast MP3 {temp_mp3_path} to {final_mp3_path}: {e}")
                        else: # Delete MP3
                            if temp_mp3_path.exists():
                                try:
                                    temp_mp3_path.unlink() # Replaced os.remove
                                    logger.info(f"Successfully deleted podcast MP3: {temp_mp3_path}")
                                except OSError as e:
                                    logger.error(f"Failed to delete podcast MP3 file {temp_mp3_path}: {e}")
                        
                        notifications.send_to_discord(config.DISCORD_WEBHOOK_URL, final_output_txt_path, episode_title)
                        podcast_processing.save_processed_episode(episode_guid)
                        processed_episode_guids_set.add(episode_guid)
                        logger.info(f"Successfully processed podcast episode: '{episode_title}' (GUID: {episode_guid})")

                        # Check import folder after processing this podcast episode
                        if config.IMPORT_DIR and transcription_model_obj:
                            logger.info(f"--- Checking import folder (after podcast episode: {episode_title}) ---")
                            import_handler.process_import_folder(
                                transcription_model_obj,
                                transcription.transcribe_audio,
                                notifications.send_to_discord
                            )
                except podcast_processing.feedparser.FeedParserError as fpe: # Catch specific feedparser error
                    logger.error(f"Error parsing feed {feed_url}: {fpe}")
                except requests.exceptions.ConnectionError as rce:
                    logger.error(f"Connection error for feed {feed_url}: {rce}. Will retry next cycle.")
                except Exception as e:
                    logger.error(f"Major error processing feed {feed_url}: {e}", exc_info=True)
            
            logger.info(f"--- Podcast feed check cycle complete. Processed {new_episodes_processed_this_cycle} new podcast episodes this cycle. ---")
        elif not config.IMPORT_DIR_ENV: 
             logger.info("No podcast feeds or import directory configured. Script will sleep.")

        # Determine sleep interval
        current_sleep_interval = config.CHECK_INTERVAL_SECONDS
        if config.IMPORT_DIR_ENV and not config.PODCAST_FEEDS_ENV: # Only import dir is active
            current_sleep_interval = config.IMPORT_CHECK_INTERVAL_SECONDS
            logger.info(f"Only import directory is active. Using import check interval: {current_sleep_interval} seconds.")
        
        logger.info(f"Sleeping for {current_sleep_interval} seconds...")
        time_module.sleep(current_sleep_interval)

if __name__ == "__main__":
    # Basic check for critical configurations before starting
    if not config.PODCAST_FEEDS_ENV and not config.IMPORT_DIR_ENV:
        logger.critical("CRITICAL: Neither PODCAST_FEEDS nor IMPORT_DIR environment variables are set. At least one must be configured. Exiting.")
        sys.exit(1)
    
    logger.info(f"Application Name: Podcast Transcriber") # Example of a general log
    logger.info(f"Version: 1.0_refactored") # Example
    logger.info(f"Script starting: main.py")
    logger.info(f"--- System Configuration ---")
    logger.info(f"Transcription Engine: {config.TRANSCRIPTION_ENGINE}")
    logger.info(f"Whisper Model: {config.WHISPER_MODEL}, Device: {config.DEVICE}")
    if config.TRANSCRIPTION_ENGINE == "faster-whisper":
        logger.info(f"Faster-Whisper Compute Type: {config.COMPUTE_TYPE}")
    logger.info(f"Keep MP3s from Podcasts: {config.KEEP_MP3}")
    logger.info(f"Discord Notifications: {'Enabled' if config.DISCORD_WEBHOOK_URL else 'Disabled'}")
    logger.info(f"Podcast Feeds configured: {True if config.podcast_urls else False}")
    logger.info(f"Import Directory configured: {config.IMPORT_DIR if config.IMPORT_DIR else 'Disabled'}")
    logger.info(f"Output Directory: {config.OUTPUT_DIR}")
    logger.info(f"----------------------------")

    ensure_directories()

    transcription_model_obj = transcription.load_transcription_model()
    if not transcription_model_obj:
        logger.critical("Failed to load transcription model. Please check logs. Exiting.")
        sys.exit(1)

    processed_episode_guids_set = podcast_processing.load_processed_episodes()
    
    try:
        main_loop(transcription_model_obj, processed_episode_guids_set)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received (KeyboardInterrupt). Exiting gracefully.")
    except Exception as e:
        logger.critical(f"An uncaught exception occurred in the main loop: {e}", exc_info=True)
    finally:
        logger.info("Application shutting down.")