import os
import datetime
import logging
import json
from bot_app.core.config import LOG_DIR
from bot_app.integrations.ai_client import ask_ai

logger = logging.getLogger(__name__)

async def generate_news_json(guild_id: int, guild_name: str, days: int = 1) -> dict:
    # 1. Collect logs for N days
    collected_lines = []
    
    def safe_dirname(name: str) -> str:
        keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
        return "".join(c if c in keep else "_" for c in (name or "guild")).strip() or "guild"

    # Iterate backwards (from oldest to newest within range)
    # Actually logic: we want [Day-4, Day-3, ... Today]
    dates = [datetime.datetime.now() - datetime.timedelta(days=i) for i in range(days-1, -1, -1)]
    
    found_any = False
    
    for dt in dates:
        date_str = dt.strftime("%Y-%m-%d")
        log_path = os.path.join(LOG_DIR, date_str, safe_dirname(guild_name), f"{date_str}.log")
        
        if os.path.exists(log_path):
            found_any = True
            try:
                day_lines = []
                with open(log_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if not line or "Sink received" in line or "Processing chunk" in line: continue
                        # Remove date part "2025-12-23 10:00" -> "10:00"
                        if len(line) > 11 and line[4] == '-' and line[7] == '-':
                            line = line[11:] 
                        day_lines.append(f"[{date_str}] {line}")
                
                # If collecting many days, take only last ~500 lines per day to save tokens
                limit_per_day = 500 if days > 1 else 2000
                collected_lines.extend(day_lines[-limit_per_day:])
                
            except Exception as e:
                logger.error(f"Error reading {log_path}: {e}")

    if not found_any:
        return {"error": f"Логи за последние {days} дней не найдены."}

    if len(collected_lines) < 10:
        return {"error": "Слишком мало событий для анализа."}

    # Global Limit (e.g. 40k chars)
    full_text = "\n".join(collected_lines)
    if len(full_text) > 40000:
        full_text = "...(старые записи пропущены)...\n" + full_text[-40000:]

    logger.info(f"Sending {len(full_text)} chars of logs to AI for news (days={days}).")

    period_str = "сегодня" if days == 1 else f"последние {days} дней"

    prompt = f"""
    Используй эти логи сервера "{guild_name}" за {period_str} для создания выпуска новостей:
    --- НАЧАЛО ЛОГОВ ---
    {full_text}
    --- КОНЕЦ ЛОГОВ ---
    
    ЗАДАЧА: Напиши ОБШИРНЫЙ, СМЕШНОЙ и САРКАСТИЧНЫЙ отчет о событиях за весь период.
    Выдели главные интриги, конфликты или смешные моменты, которые длились несколько дней (если есть).
    
    ВЕРНИ ТОЛЬКО JSON (СТРОГО):
    {{
        "headline": "ГРОМКИЙ ЗАГОЛОВОК (КАПСОМ)",
        "summary": ["Факт 1", "Факт 2 (развитие событий)", "Факт 3 (финал)"],
        "article": "Текст статьи. Опиши хронологию событий, если это уместно.",
        "hero": "Никнейм героя недели/дня",
        "quote": "Лучшая цитата за все время"
    }}
    """

    try:
        raw_resp = await ask_ai(prompt, system_prompt="Ты редактор новостей. Ты всегда отвечаешь только в формате JSON.")
        
        # Clean response
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
        return {"error": "ИИ вернул текст вместо данных."}
    except Exception as e:
        logger.error(f"News gen error: {e}")
        return {"error": f"Ошибка AI: {e}"}