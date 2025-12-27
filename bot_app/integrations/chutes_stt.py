import logging
import os
import requests
from bot_app.core import state

logger = logging.getLogger(__name__)

def transcribe_file_chutes_sync(file_path: str, offset: float, user_name: str, duration: float) -> list[tuple[float, str]]:
    """
    Synchronous transcription using Chutes.ai (Whisper Large v3 Turbo).
    """
    # 1. Get Key
    key = os.getenv("CHUTES_API_KEY")
    if not key:
        # Fallback to generic AI key if user put it there
        key = os.getenv("AI_API_KEY")
    
    if not key:
        logger.error("Chutes STT: CHUTES_API_KEY not found.")
        return []

    # 2. Config
    url = "https://chutes.ai/api/v1/audio/transcriptions"
    model = "openai/whisper-large-v3-turbo"

    headers = {
        "Authorization": f"Bearer {key}"
    }

    try:
        with open(file_path, "rb") as f:
            files = {
                "file": ("audio.wav", f, "audio/wav"),
                "model": (None, model),
                "language": (None, "ru"), # Hint Russian for better accuracy
                "response_format": (None, "verbose_json")
            }
            
            # Request
            resp = requests.post(url, headers=headers, files=files, timeout=60)
            
            if resp.status_code != 200:
                logger.error(f"Chutes STT Error {resp.status_code}: {resp.text[:200]}")
                return []
            
            data = resp.json()
            text = data.get("text", "").strip()
            
            if text:
                # Whisper usually gives clean text.
                # Timestamps are available in segments if we need them, but for now we use offset.
                return [(offset, text)]

    except Exception as e:
        logger.error(f"Chutes STT Request Failed: {e}")
        
    return []
