"""
Async wrappers for Azure STT to integrate with rate limiting.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Global rate limiter - will be injected by bot
_azure_rate_limiter = None
_assembly_rate_limiter = None


def set_rate_limiters(azure_limiter, assembly_limiter):
    """
    Set global rate limiters for STT APIs.
    Called from bot_entry.py.
    """
    global _azure_rate_limiter, _assembly_rate_limiter
    _azure_rate_limiter = azure_limiter
    _assembly_rate_limiter = assembly_limiter
    logger.info("STT rate limiters configured")


async def transcribe_azure_async(filename: str, abs_chunk_start_ts: float, user_name: str, duration_sec: float):
    """
    Async wrapper for Azure STT with rate limiting.
    """
    from bot_app.integrations.azure_stt import transcribe_file_azure_sentences
    
    # Acquire rate limit slot
    if _azure_rate_limiter:
        await _azure_rate_limiter.acquire()
    
    # Run in executor to avoid blocking
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        transcribe_file_azure_sentences,
        filename,
        abs_chunk_start_ts,
        user_name,
        duration_sec
    )
    
    return result


async def transcribe_assembly_async(file_source, abs_chunk_start_ts: float, user_name: str, duration_sec: float):
    """
    Async wrapper for AssemblyAI STT with rate limiting.
    """
    from bot_app.integrations.assembly_stt import transcribe_file_assembly_sentences
    
    # Acquire rate limit slot
    if _assembly_rate_limiter:
        await _assembly_rate_limiter.acquire()
    
    # Run in executor to avoid blocking
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        transcribe_file_assembly_sentences,
        file_source,
        abs_chunk_start_ts,
        user_name,
        duration_sec
    )
    
    return result
