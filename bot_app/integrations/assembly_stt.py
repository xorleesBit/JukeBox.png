import os
import logging
import asyncio
import time
from bot_app.core.config import TOKEN # We'll add ASSEMBLY_KEY to config.py later

logger = logging.getLogger(__name__)

# We will read key from config
ASSEMBLYAI_KEY = os.getenv("ASSEMBLYAI_API_KEY")

try:
    import assemblyai as aai
    if ASSEMBLYAI_KEY:
        aai.settings.api_key = ASSEMBLYAI_KEY
except ImportError:
    aai = None

def transcribe_file_assembly_sentences(filename: str, abs_chunk_start_ts: float, user_name: str, duration_sec: float):
    """
    Simulates Azure's sentence-level transcription using AssemblyAI.
    Runs in ThreadPoolExecutor.
    """
    if not ASSEMBLYAI_KEY or aai is None:
        logger.error("AssemblyAI not configured.")
        return []

    if not os.path.exists(filename):
        return []

    logger.info(f"Starting AssemblyAI STT for {filename} ({user_name})")

    try:
        # 1. Configure
        config = aai.TranscriptionConfig(
            language_code=os.getenv("AZURE_LANGUAGE", "ru")[:2], # Assembly uses 2-char codes (ru, en)
            speech_model=aai.SpeechModel.nano, # 'nano' is cheaper/faster, 'universal' is better.
            punctuate=True,
            format_text=True
        )
        
        # 2. Transcribe (Blocking in this thread)
        transcriber = aai.Transcriber(config=config)
        transcript = transcriber.transcribe(filename)

        if transcript.status == aai.TranscriptStatus.error:
            logger.error(f"AssemblyAI Error: {transcript.error}")
            return []

        # 3. Process Sentences
        # AssemblyAI provides transcript.get_sentences()
        sentences = transcript.get_sentences()
        
        results = []
        for sent in sentences:
            # Assembly timestamps are in milliseconds
            start_offset_sec = sent.start / 1000.0
            results.append((
                abs_chunk_start_ts + start_offset_sec,
                f"{user_name}: {sent.text}"
            ))
            
        logger.info(f"AssemblyAI finished: {len(results)} sentences.")
        return results

    except Exception as e:
        logger.error(f"AssemblyAI Exception: {e}")
        return []
