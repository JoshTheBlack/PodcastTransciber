# app/transcription.py
import logging
from pathlib import Path
import shutil
import os # Added for os.getenv

import config
import utils

logger = logging.getLogger(__name__)

_WhisperModel = None
_openai_whisper = None

# Conditional imports for engine libraries (done at module level based on config for simplicity here)
# Entrypoint will ensure these are installed before Python script runs.
if config.TRANSCRIPTION_ENGINE == "faster-whisper":
    try:
        from faster_whisper import WhisperModel as _WhisperModel_imported
        _WhisperModel = _WhisperModel_imported
    except ImportError:
        # This error should ideally be caught by entrypoint pre-flight check
        logger.error("faster-whisper library not found by Python script. Entrypoint should have installed it.")
elif config.TRANSCRIPTION_ENGINE == "openai-whisper":
    try:
        import whisper as _openai_whisper_imported
        _openai_whisper = _openai_whisper_imported
    except ImportError:
        logger.error("openai-whisper library not found by Python script. Entrypoint should have installed it.")

def load_transcription_model():
    model = None
    engine_name = config.TRANSCRIPTION_ENGINE
    model_name = config.WHISPER_MODEL
    device = config.DEVICE
    compute_type = config.COMPUTE_TYPE # For faster-whisper

    # Get model cache paths from environment variables (set by entrypoint.sh)
    openai_cache_dir = os.getenv("WHISPER_OPENAI_CACHE_DIR")
    faster_cache_dir = os.getenv("WHISPER_FASTER_CACHE_DIR")

    try:
        logger.info(f"Attempting to load model '{model_name}' for engine '{engine_name}' on device '{device}'.")
        if engine_name == "faster-whisper":
            if not _WhisperModel:
                logger.error("Faster-whisper engine selected, but model class not available (import failed).")
                return None
            logger.info(f"Using faster-whisper cache path: {faster_cache_dir or 'default'}")
            model = _WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=faster_cache_dir # Use this to specify cache/download directory
            )
        elif engine_name == "openai-whisper":
            if not _openai_whisper:
                logger.error("OpenAI-Whisper engine selected, but library not available (import failed).")
                return None
            logger.info(f"Using openai-whisper cache path: {openai_cache_dir or 'default (~/.cache/whisper)'}")
            # openai-whisper uses XDG_CACHE_HOME or specific download_root in load_model
            # Setting XDG_CACHE_HOME in entrypoint is one way. Or pass download_root if supported.
            # For openai-whisper, load_model has a 'download_root' parameter.
            model = _openai_whisper.load_model(
                model_name,
                device=device,
                download_root=openai_cache_dir # Specify download/cache directory
            )
        else:
            logger.error(f"Cannot load model: Unsupported TRANSCRIPTION_ENGINE: {engine_name}")
            return None
        logger.info(f"Transcription model '{model_name}' for engine '{engine_name}' loaded successfully.")
        return model
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to load transcription model ({engine_name}, {model_name}): {e}", exc_info=True)
        return None

# Rest of transcription.py (transcribe_audio_faster_whisper, transcribe_audio_openai_whisper, transcribe_audio)
# remains the same as the version with direct imports ('import config', 'import utils')
# and using utils.format_timestamp, config.DEBUG_LOGGING.

def transcribe_audio_faster_whisper(model: '_WhisperModel', audio_path: Path, final_output_txt_path: Path):
    temp_output_txt_path = final_output_txt_path.with_suffix(final_output_txt_path.suffix + '.processing')
    try:
        final_output_txt_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"[faster-whisper] Starting transcription for: {audio_path} -> {temp_output_txt_path}")
        segments_generator, info = model.transcribe(str(audio_path), beam_size=5)
        
        logger.info(f"[faster-whisper] Detected language '{info.language}' with probability {info.language_probability:.2f}")
        logger.info(f"[faster-whisper] Audio duration processed: {utils.format_timestamp(info.duration)}")
        
        segment_count = 0
        with open(temp_output_txt_path, 'w', encoding='utf-8') as f:
            for segment in segments_generator:
                start_str = utils.format_timestamp(segment.start)
                end_str = utils.format_timestamp(segment.end)
                segment_text = segment.text.strip()
                f.write(f"[{start_str} --> {end_str}] {segment_text}\n")
                segment_count += 1
                if config.DEBUG_LOGGING:
                    logger.debug(f"[faster-whisper] Segment {segment_count}: [{start_str} --> {end_str}] {segment_text}")
        
        shutil.move(str(temp_output_txt_path), str(final_output_txt_path))
        logger.info(f"[faster-whisper] Transcription with {segment_count} segments saved to {final_output_txt_path}")
        return True
    except Exception as e:
        logger.error(f"[faster-whisper] Failed to transcribe {audio_path}: {e}", exc_info=True)
        if temp_output_txt_path.exists():
            try: temp_output_txt_path.unlink()
            except OSError as oe: logger.error(f"Error deleting temp transcript file {temp_output_txt_path} on error: {oe}")
        return False

def transcribe_audio_openai_whisper(model, audio_path: Path, final_output_txt_path: Path):
    temp_output_txt_path = final_output_txt_path.with_suffix(final_output_txt_path.suffix + '.processing')
    try:
        final_output_txt_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"[openai-whisper] Starting transcription for: {audio_path} -> {temp_output_txt_path}")
        result = model.transcribe(str(audio_path), verbose=config.DEBUG_LOGGING) 
        logger.info(f"[openai-whisper] Detected language '{result['language']}'")
        
        segment_count = 0
        with open(temp_output_txt_path, 'w', encoding='utf-8') as f:
            for segment in result["segments"]:
                start_str = utils.format_timestamp(segment.start)
                end_str = utils.format_timestamp(segment.end)
                segment_text = segment['text'].strip()
                f.write(f"[{start_str} --> {end_str}] {segment_text}\n")
                segment_count += 1
                if config.DEBUG_LOGGING: 
                    logger.debug(f"[openai-whisper] Script logged Segment {segment_count}: [{start_str} --> {end_str}] {segment_text}")
        shutil.move(str(temp_output_txt_path), str(final_output_txt_path))
        logger.info(f"[openai-whisper] Transcription with {segment_count} segments saved to {final_output_txt_path}")
        return True
    except Exception as e:
        logger.error(f"[openai-whisper] Failed to transcribe {audio_path}: {e}", exc_info=True)
        if temp_output_txt_path.exists():
            try: temp_output_txt_path.unlink()
            except OSError as oe: logger.error(f"Error deleting temp transcript file {temp_output_txt_path} on error: {oe}")
        return False

def transcribe_audio(model, audio_path: Path, output_txt_path: Path):
    if config.TRANSCRIPTION_ENGINE == "faster-whisper":
        return transcribe_audio_faster_whisper(model, audio_path, output_txt_path)
    elif config.TRANSCRIPTION_ENGINE == "openai-whisper":
        return transcribe_audio_openai_whisper(model, audio_path, output_txt_path)
    else:
        logger.error(f"Unknown transcription engine '{config.TRANSCRIPTION_ENGINE}' in transcribe_audio call.")
        return False