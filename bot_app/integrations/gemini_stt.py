import logging
import os
import time
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

def _get_google_key():
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        fallback = os.getenv("AI_API_KEY", "")
        if fallback.startswith("AIza"):
            key = fallback
    return key

def transcribe_file_gemini_sync(file_path: str, offset: float, user_name: str, duration: float) -> list[tuple[float, str]]:
    """
    Synchronous transcription using NEW Google GenAI SDK (google-genai).
    """
    api_key = _get_google_key()
    if not api_key:
        logger.error("Gemini STT: GOOGLE_API_KEY not found in .env")
        return []

    client = genai.Client(api_key=api_key)
    
    try:
        # 1. Read Audio Bytes
        with open(file_path, "rb") as f:
            audio_data = f.read()

        # 2. Generate with INLINE data (No upload_file overhead)
        # This bypasses the strict File API rate limits
        
        prompt = """
        Transcribe this audio verbatim.
        - Output ONLY the text.
        - If silent, output nothing.
        - Mark emotions in [brackets].
        - Keep slang/swear words.
        """

        # Retry logic for Inference API (not File API)
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=[
                        types.Content(
                            parts=[
                                types.Part.from_text(text=prompt),
                                types.Part.from_bytes(
                                    data=audio_data,
                                    mime_type="audio/wav"
                                )
                            ]
                        )
                    ]
                )

                if response and response.text:
                    text = response.text.strip()
                    if text:
                        return [(offset, text)]
                return [] # Success but empty/silence
                
            except Exception as e:
                # Check for 429
                if "429" in str(e):
                    wait = (attempt + 1) * 3
                    logger.warning(f"Gemini STT 429 (Attempt {attempt+1}/3). Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    logger.error(f"Gemini STT New SDK Error: {e}")
                    break
        
        # If we reached here, all attempts failed
        logger.error("Gemini STT Failed after retries. Signaling fallback.")
        return None 
                
    except Exception as e:
        logger.error(f"Gemini STT Critical Error: {e}")
        
    return None

async def transcribe_file_gemini(file_path: str, offset: float, user_name: str, duration: float) -> list[tuple[float, str]]:
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, transcribe_file_gemini_sync, file_path, offset, user_name, duration)