# app/utils.py
import re
from datetime import datetime, timezone, timedelta

def sanitize_filename(filename_str: str) -> str:
    """Removes or replaces characters unsafe for filenames from a string."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", str(filename_str))
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized[:200] # Limit length

def format_timestamp(seconds: float) -> str:
    """Converts seconds to HH:MM:SS.mmm format."""
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)
    
    td = timedelta(milliseconds=milliseconds)
    
    hours, remainder = divmod(td.seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    millisecs = td.microseconds // 1000 # Extract milliseconds part from microseconds

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millisecs:03d}"