import aiohttp
import asyncio
import logging
import time
from bot_app.core import state # Access global state

logger = logging.getLogger(__name__)

# --- Circuit Breaker State ---
_circuit_errors = 0
_circuit_open_ts = 0
CIRCUIT_THRESHOLD = 5
CIRCUIT_TIMEOUT = 60

async def ask_ai(prompt: str, system_prompt: str = None, retries: int = 3) -> str:
    """
    Generic OpenAI-compatible completion function.
    Uses dynamic configuration from state.ai_manager.
    """
    global _circuit_errors, _circuit_open_ts

    # 0. Check Circuit Breaker
    if time.time() - _circuit_open_ts < CIRCUIT_TIMEOUT:
        return "⚠️ AI Circuit Open (API Unstable). Try again later."

    # 1. Get Config
    provider = None
    if state.ai_manager:
        key = state.ai_manager.current_key
        base_url = state.ai_manager.current_url
        model = state.ai_manager.current_model
        provider = state.ai_manager.current_provider
    else:
        # Fallback (Should rarely happen)
        from bot_app.core.config import AI_API_KEY, AI_MODEL, AI_BASE_URL
        key = AI_API_KEY
        base_url = AI_BASE_URL
        model = AI_MODEL

    if not key:
        return "⚠️ Ошибка: AI API Key не найден (проверьте настройки /ai_setup)."

    if not system_prompt:
        system_prompt = "You are a helpful assistant. Respond in Russian."

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    
    # Provider-specific headers
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/loger-bot"
        headers["X-Title"] = "LogerBot"
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 2048
    }

    session = state.http_session

    for attempt in range(retries):
        try:
            # Use global session if available, else create temp one (fallback)
            if session and not session.closed:
                async with session.post(url, json=data, headers=headers) as resp:
                    if resp.status == 429:
                        wait_time = (attempt + 1) * 5
                        logger.warning(f"AI Rate Limit (429). Waiting {wait_time}s... (Attempt {attempt+1}/{retries})")
                        await asyncio.sleep(wait_time)
                        continue
                        
                    if resp.status != 200:
                        _circuit_errors += 1
                        if _circuit_errors >= CIRCUIT_THRESHOLD:
                            _circuit_open_ts = time.time()
                            logger.error(f"AI Circuit Breaker TRIPPED. Pause for {CIRCUIT_TIMEOUT}s.")
                        
                        text = await resp.text()
                        logger.warning(f"AI API Warning: {resp.status} (URL: {url}) - {text[:200]}...")
                        return f"⚠️ Ошибка API AI: {resp.status}"
                    
                    # Success
                    _circuit_errors = 0
                    result = await resp.json()
                    if 'choices' in result and len(result['choices']) > 0:
                        return result['choices'][0]['message']['content']
                    else:
                        return "⚠️ Пустой ответ от API."
            else:
                # Fallback to per-request session if global is missing
                async with aiohttp.ClientSession() as temp_session:
                    async with temp_session.post(url, json=data, headers=headers) as resp:
                        if resp.status == 429:
                            wait_time = (attempt + 1) * 5
                            await asyncio.sleep(wait_time)
                            continue
                        if resp.status != 200:
                            return f"⚠️ Ошибка API AI: {resp.status}"
                        result = await resp.json()
                        if 'choices' in result and len(result['choices']) > 0:
                            return result['choices'][0]['message']['content']
                        else:
                            return "⚠️ Пустой ответ."

        except Exception as e:
            logger.exception("AI Request Failed")
            _circuit_errors += 1
            if _circuit_errors >= CIRCUIT_THRESHOLD:
                _circuit_open_ts = time.time()
                logger.error(f"AI Circuit Breaker TRIPPED on Exception. Pause for {CIRCUIT_TIMEOUT}s.")
            
            if attempt == retries - 1:
                return f"⚠️ Ошибка при запросе: {e}"
            await asyncio.sleep(2)

    return "⚠️ Ошибка: Превышен лимит запросов (Rate Limit)."