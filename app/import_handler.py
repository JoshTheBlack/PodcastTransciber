# app/import_handler.py
import logging
from pathlib import Path
import shutil

import config # For IMPORT_DIR, SUPPORTED_IMPORT_EXTENSIONS, TRANSCRIPTS_DIR, DISCORD_WEBHOOK_URL
import utils # For sanitize_filename
# For transcription and notification functions, they will be passed as arguments

logger = logging.getLogger(__name__)

def process_import_folder(
        transcription_model,
        transcribe_audio_func, # Function reference, e.g., transcription.transcribe_audio
        send_to_discord_func   # Function reference, e.g., notifications.send_to_discord
    ):
    if not config.IMPORT_DIR or not config.IMPORT_DIR.exists() or not config.IMPORT_DIR.is_dir():
        if config.IMPORT_DIR_ENV:
            logger.warning(f"Import directory '{config.IMPORT_DIR_ENV}' not found or not a directory. Skipping.")
        return 0

    processed_count = 0
    logger.info(f"Checking import folder: {config.IMPORT_DIR}")
    
    processing_temp_dir = config.IMPORT_DIR / ".processing_tmp"
    processing_temp_dir.mkdir(exist_ok=True)

    for item in config.IMPORT_DIR.iterdir():
        if item.is_file() and item.suffix.lower() in config.SUPPORTED_IMPORT_EXTENSIONS:
            logger.info(f"Found import file: {item.name}")
            
            temp_audio_path = processing_temp_dir / item.name
            try:
                shutil.move(str(item), str(temp_audio_path))
            except Exception as e:
                logger.error(f"Failed to move import file {item.name} to processing dir: {e}. Skipping.")
                continue

            original_file_title = temp_audio_path.stem
            transcript_filename_base = utils.sanitize_filename(original_file_title)
            final_transcript_txt_path = config.TRANSCRIPTS_DIR / f"{transcript_filename_base}.txt"

            if final_transcript_txt_path.exists():
                logger.warning(f"Transcript for imported file '{temp_audio_path.name}' already exists. Deleting imported audio.")
                try: temp_audio_path.unlink()
                except OSError as e: logger.error(f"Error deleting already processed imported audio {temp_audio_path.name}: {e}")
                continue

            logger.info(f"Processing imported file: {temp_audio_path.name}")
            config.TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

            success = transcribe_audio_func(
                transcription_model,
                temp_audio_path,
                final_transcript_txt_path
            )
            
            if success:
                logger.info(f"Successfully transcribed imported file: {temp_audio_path.name} to {final_transcript_txt_path}")
                if config.DISCORD_WEBHOOK_URL:
                    send_to_discord_func(config.DISCORD_WEBHOOK_URL, final_transcript_txt_path, original_file_title)
                try:
                    temp_audio_path.unlink()
                    logger.info(f"Deleted imported audio file: {temp_audio_path.name} after processing.")
                except OSError as e:
                    logger.error(f"Error deleting imported audio file {temp_audio_path.name}: {e}")
                processed_count += 1
            else:
                logger.error(f"Failed to transcribe imported file: {temp_audio_path.name}. Moving it back to import root.")
                try:
                    shutil.move(str(temp_audio_path), str(config.IMPORT_DIR / temp_audio_path.name))
                except Exception as e:
                    logger.error(f"Could not move failed import {temp_audio_path.name} back to root: {e}.")
    try:
        if not any(processing_temp_dir.iterdir()):
            processing_temp_dir.rmdir()
    except OSError:
        pass # Directory not empty or other error
        
    if processed_count > 0:
        logger.info(f"Processed {processed_count} file(s) from import folder.")
    return processed_count