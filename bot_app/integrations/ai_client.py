import aiohttp
import asyncio
import logging
from bot_app.core.config import AI_API_KEY, AI_MODEL, AI_BASE_URL
from bot_app.core import state # Access global state

logger = logging.getLogger(__name__)

async def ask_ai(prompt: str, system_prompt: str = None, retries: int = 3) -> str:
    """
    Generic OpenAI-compatible completion function.
    Uses global shared aiohttp session if available.
    """
    if not AI_API_KEY:
        return "⚠️ Ошибка: Не задан AI_API_KEY в .env"

    if not system_prompt:
        system_prompt = "You are a helpful assistant. Respond in Russian."

    url = f"{AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": AI_MODEL,
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
                        text = await resp.text()
                        logger.error(f"AI API Error: {resp.status} (URL: {url}) - {text[:200]}...")
                        return f"⚠️ Ошибка API AI: {resp.status}"
                    
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
            if attempt == retries - 1:
                return f"⚠️ Ошибка при запросе: {e}"
            await asyncio.sleep(2)

    return "⚠️ Ошибка: Превышен лимит запросов (Rate Limit)."