import os
import logging
import asyncio
import time
from bot_app.core.config import TOKEN 

logger = logging.getLogger(__name__)

# We will read key from config
ASSEMBLYAI_KEY = os.getenv("ASSEMBLYAI_API_KEY")

try:
    import assemblyai as aai
    if ASSEMBLYAI_KEY:
        aai.settings.api_key = ASSEMBLYAI_KEY
except ImportError:
    aai = None

def transcribe_file_assembly_sentences(file_source, abs_chunk_start_ts: float, user_name: str, duration_sec: float):
    """
    Simulates Azure's sentence-level transcription using AssemblyAI.
    Runs in ThreadPoolExecutor.
    
    file_source: str (path) OR file-like object (io.BytesIO)
    """
    if not ASSEMBLYAI_KEY or aai is None:
        logger.error("AssemblyAI not configured.")
        return []

    # If file_source is a path, check existence
    if isinstance(file_source, str) and not os.path.exists(file_source):
        return []

    logger.info(f"Starting AssemblyAI STT for {user_name}...")

    try:
        # 1. Configure
        config = aai.TranscriptionConfig(
            language_code=os.getenv("AZURE_LANGUAGE", "ru")[:2],
            speech_model=aai.SpeechModel.nano,
            punctuate=True,
            format_text=True
        )
        
        # 2. Transcribe (Blocking in this thread)
        transcriber = aai.Transcriber(config=config)
        
        # AssemblyAI SDK accepts file paths or file-like objects directly
        transcript = transcriber.transcribe(file_source)

        if transcript.status == aai.TranscriptStatus.error:
            logger.error(f"AssemblyAI Error: {transcript.error}")
            return []

        # 3. Process Sentences
        try:
            sentences = transcript.get_sentences()
            
            results = []
            for sent in sentences:
                # Assembly timestamps are in milliseconds
                start_offset_sec = sent.start / 1000.0
                results.append((
                    abs_chunk_start_ts + start_offset_sec,
                    f"{user_name}: {sent.text}"
                ))
        except Exception as e:
            logger.warning(f"AssemblyAI get_sentences() failed: {e}. Fallback to raw text.")
            results = []
            if transcript.text:
                 results.append((
                    abs_chunk_start_ts,
                    f"{user_name}: {transcript.text}"
                ))
            
        logger.info(f"AssemblyAI finished: {len(results)} sentences/segments.")
        return results

    except Exception as e:
        logger.error(f"AssemblyAI Exception: {e}")
        return []