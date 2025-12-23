import os
import datetime
import logging
import json
from bot_app.core.config import LOG_DIR
from bot_app.integrations.ai_client import ask_ai

logger = logging.getLogger(__name__)

async def generate_daily_news_json(guild_id: int, guild_name: str) -> dict:
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    def safe_dirname(name: str) -> str:
        keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
        return "".join(c if c in keep else "_" for c in (name or "guild")).strip() or "guild"
        
    log_path = os.path.join(LOG_DIR, today, safe_dirname(guild_name), f"{today}.log")
    
    if not os.path.exists(log_path):
        return {"error": f"Лог за {today} еще не создан."}

    lines = []
    try:
        with open(log_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                # Убираем только совсем бесполезный шум
                if "Sink received" in line: continue 
                # Сокращаем формат времени для экономии токенов [01:02:03] -> [01:02]
                line = line.replace("2025-12-23 ", "") # убираем дату
                lines.append(line)
    except Exception as e:
        return {"error": f"Ошибка чтения лога: {e}"}

    if len(lines) < 5:
        return {"error": "Слишком мало событий в логе для анализа."}

    # Берем последние 200 строк лога (самое важное)
    content = "\n".join(lines[-200:])
    
    logger.info(f"Sending {len(content)} chars of logs to AI for news.")

    prompt = f"""
    Используй эти логи сервера "{guild_name}" для создания выпуска новостей:
    --- НАЧАЛО ЛОГОВ ---
    {content}
    --- КОНЕЦ ЛОГОВ ---
    
    ЗАДАЧА: Напиши смешной отчет о событиях в формате JSON. 
    Если событий мало, обшути тишину на сервере.
    
    ВЕРНИ ТОЛЬКО JSON (СТРОГО):
    {{
        "headline": "ЗАГОЛОВОК",
        "summary": ["факт 1", "факт 2"],
        "article": "текст статьи",
        "hero": "никнейм",
        "quote": "цитата"
    }}
    """

    try:
        raw_resp = await ask_ai(prompt, system_prompt="Ты редактор новостей. Ты всегда отвечаешь только в формате JSON.")
        
        # Очистка ответа от возможного мусора
        clean_resp = raw_resp.strip()
        if "```json" in clean_resp:
            clean_resp = clean_resp.split("```json")[1].split("```")[0]
        elif "```" in clean_resp:
            clean_resp = clean_resp.split("```")[1].split("```")[0]
            
        start_idx = clean_resp.find("{")
        end_idx = clean_resp.rfind("}")
        if start_idx != -1 and end_idx != -1:
            clean_resp = clean_resp[start_idx:end_idx+1]
        
        return json.loads(clean_resp)
    except json.JSONDecodeError:
        logger.error(f"AI returned non-JSON: {raw_resp}")
        return {"error": "ИИ вернул текст вместо данных. Попробуйте еще раз."}
    except Exception as e:
        logger.error(f"News gen error: {e}")
        return {"error": "Не удалось связаться с редакцией (AI error)."}
