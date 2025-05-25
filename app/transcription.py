# app/transcription.py
import logging
from pathlib import Path
import shutil

# Conditional imports for transcription engines
import config # For TRANSCRIPTION_ENGINE, WHISPER_MODEL, DEVICE, COMPUTE_TYPE, DEBUG_LOGGING
import utils # For format_timestamp

logger = logging.getLogger(__name__)

# Dynamically import based on config - this needs to be handled carefully for type hinting if strict
_WhisperModel = None
_openai_whisper = None

if config.TRANSCRIPTION_ENGINE == "faster-whisper":
    try:
        from faster_whisper import WhisperModel as _WhisperModel_imported
        _WhisperModel = _WhisperModel_imported
    except ImportError:
        logger.error("faster-whisper library not found. Please install it.")
        _WhisperModel = None
elif config.TRANSCRIPTION_ENGINE == "openai-whisper":
    try:
        import whisper as _openai_whisper_imported
        _openai_whisper = _openai_whisper_imported
    except ImportError:
        logger.error("openai-whisper library not found. Please install it.")
        _openai_whisper = None
else: # Fallback or error for unknown engine
    logger.warning(f"Unknown TRANSCRIPTION_ENGINE: {config.TRANSCRIPTION_ENGINE}. Transcription will not work.")


def load_transcription_model():
    """Loads the specified transcription model."""
    model = None
    engine_name = config.TRANSCRIPTION_ENGINE
    model_name = config.WHISPER_MODEL
    device = config.DEVICE
    compute_type = config.COMPUTE_TYPE

    try:
        if engine_name == "faster-whisper":
            if not _WhisperModel:
                raise RuntimeError("Faster-whisper model class not imported.")
            logger.info(f"Loading faster-whisper model '{model_name}' (device={device}, compute_type={compute_type})...")
            model = _WhisperModel(model_name, device=device, compute_type=compute_type)
        elif engine_name == "openai-whisper":
            if not _openai_whisper:
                raise RuntimeError("OpenAI-Whisper library not imported.")
            logger.info(f"Loading openai-whisper model '{model_name}' (device={device})...")
            model = _openai_whisper.load_model(model_name, device=device)
        else:
            logger.error(f"Cannot load model: Unsupported TRANSCRIPTION_ENGINE: {engine_name}")
            return None
        logger.info("Transcription model loaded successfully.")
        return model
    except Exception as e:
        logger.error(f"Failed to load transcription model ({engine_name}, {model_name}): {e}. Exiting.", exc_info=True)
        return None


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
    # model type for openai-whisper is whisper.model.Whisper
    temp_output_txt_path = final_output_txt_path.with_suffix(final_output_txt_path.suffix + '.processing')
    try:
        final_output_txt_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"[openai-whisper] Starting transcription for: {audio_path} -> {temp_output_txt_path}")
        result = model.transcribe(str(audio_path), verbose=config.DEBUG_LOGGING) 
        logger.info(f"[openai-whisper] Detected language '{result['language']}'")
        
        segment_count = 0
        with open(temp_output_txt_path, 'w', encoding='utf-8') as f:
            for segment in result["segments"]:
                start_str = utils.format_timestamp(segment["start"])
                end_str = utils.format_timestamp(segment["end"])
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