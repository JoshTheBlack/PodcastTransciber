# app/logger_setup.py
import logging
import os
import sys
import config # Import from our config module

def setup_logging():
    """Sets up global logging configuration."""
    log_level = logging.DEBUG if config.DEBUG_LOGGING else logging.INFO
    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
                        stream=sys.stdout)
    
    # Force python stdout/stderr streams to be unbuffered
    os.environ['PYTHONUNBUFFERED'] = '1'
    
    initial_logger = logging.getLogger(__name__)
    initial_logger.info(f"Logging initialized. Debug logging enabled: {config.DEBUG_LOGGING}")
    initial_logger.info(f"Timezone: {config.TZ}") # Log timezone