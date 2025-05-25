# app/notifications.py
import logging
from pathlib import Path
import requests
import json

logger = logging.getLogger(__name__)

def send_to_discord(webhook_url: str, file_path: Path, message_title: str):
    if not webhook_url:
        logger.debug("Discord webhook URL not set. Skipping notification.")
        return
    
    if not file_path.exists():
        logger.error(f"Discord: Transcript file not found at {file_path}, cannot send.")
        return

    try:
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        discord_message_content = f"Transcription complete for: **{message_title}**"
        
        if file_size_mb > 7.8:
            logger.warning(f"Discord: Transcript file {file_path.name} is ~{file_size_mb:.2f}MB, sending message without file.")
            payload = {"content": f"{discord_message_content}\n(Transcript `{file_path.name}` too large to attach: {file_size_mb:.2f}MB)"}
            response = requests.post(webhook_url, json=payload, timeout=10)
        else:
            with open(file_path, 'rb') as f:
                payload_dict = {"content": discord_message_content}
                files = {'file': (file_path.name, f, 'text/plain')}
                data_payload = {'payload_json': json.dumps(payload_dict)}
                response = requests.post(webhook_url, data=data_payload, files=files, timeout=30)
        
        response.raise_for_status()
        logger.info(f"Successfully sent notification for {file_path.name} to Discord.")
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error sending notification for {file_path.name} to Discord: {http_err}")
        if http_err.response is not None:
            logger.error(f"Discord response status: {http_err.response.status_code}")
            try:
                discord_error_details = http_err.response.json()
                logger.error(f"Discord error details: {json.dumps(discord_error_details, indent=2)}")
            except ValueError:
                logger.error(f"Discord response content: {http_err.response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error sending notification for {file_path.name} to Discord: {e}")
    except Exception as e: 
        logger.error(f"An unexpected error sending to Discord for {file_path.name}: {e}", exc_info=True)