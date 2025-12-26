import os
import datetime
import logging
import json
from bot_app.core.config import LOG_DIR
from bot_app.integrations.ai_client import ask_ai

logger = logging.getLogger(__name__)

def _extract_json_safe(text: str) -> str:
    text = text.strip()
    # Remove code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    start_brace = text.find("{")
    end_brace = text.rfind("}")
    
    if start_brace != -1 and end_brace != -1:
        return text[start_brace:end_brace+1]
    return text

async def generate_news_json(guild_id: int, guild_name: str, days: int = 1) -> dict:
    # 1. Collect logs for N days
    collected_lines = []
    
    def safe_dirname(name: str) -> str:
        keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
        return "".join(c if c in keep else "_" for c in (name or "guild")).strip() or "guild"

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
                        if len(line) > 11 and line[4] == '-' and line[7] == '-':
                            line = line[11:] 
                        
                        # FILTER CONTEXT FOR AI
                        l_low = line.lower()
                        if "joined the channel" in l_low or "left the channel" in l_low or "зашел" in l_low or "вышел" in l_low:
                            continue
                        if ": !" in line or ": /" in line:
                            continue
                            
                        day_lines.append(f"[{date_str}] {line}")
                
                # Take last 500 lines per day
                collected_lines.extend(day_lines[-500:]) 
            except Exception as e:
                logger.error(f"Error reading {log_path}: {e}")

    if not found_any:
        return {"error": f"Логи за последние {days} дней не найдены."}

    if len(collected_lines) < 5: # Lower threshold after filtering
        return {"error": "Слишком мало событий для анализа (после фильтрации команд и входов)."}

    # Global Limit: 25k chars to be safe
    full_text = "\n".join(collected_lines)
    if len(full_text) > 25000:
        full_text = "...(старые записи пропущены)...\n" + full_text[-25000:]

    logger.info(f"Sending {len(full_text)} chars of logs to AI for news (days={days}).")

    period_str = "сегодня" if days == 1 else f"последние {days} дней"

    prompt = f"""
    Используй логи сервера "{guild_name}" за {period_str}:
    --- НАЧАЛО ---
    {full_text}
    --- КОНЕЦ ---
    
    ЗАДАЧА: Напиши СМЕШНОЙ новостной дайджест в JSON.
    
    ТРЕБОВАНИЯ:
    1. Если логов много, выбери ТОЛЬКО самое важное.
    2. Стиль: ирония, сарказм.
    3. JSON должен быть валидным.
    
    ФОРМАТ (JSON):
    {{
        "headline": "ЗАГОЛОВОК КАПСОМ",
        "summary": ["Факт 1", "Факт 2", "Факт 3"],
        "article": "Текст статьи (макс 1000 знаков).",
        "hero": "Никнейм",
        "quote": "Цитата"
    }}
    """

    try:
        raw_resp = await ask_ai(prompt, system_prompt="Ты JSON-редактор. Ты не пишешь ничего, кроме JSON.")
        logger.info(f"[RAW AI NEWS]: {raw_resp[:100]}...")
        
        clean_resp = _extract_json_safe(raw_resp)
        return json.loads(clean_resp)
    except json.JSONDecodeError:
        logger.error(f"AI returned non-JSON: {raw_resp}")
        return {"error": "ИИ вернул текст. Попробуйте снова."}
    except Exception as e:
        return {"error": f"Ошибка AI: {e}"}
