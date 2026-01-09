import os
import datetime
import logging
import json
import re
from bot_app.core.config import LOG_DIR
from bot_app.integrations.ai_client import ask_ai
from bot_app.core.state import profile_manager, context_manager

logger = logging.getLogger(__name__)

def _extract_json_safe(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start:end+1]
    return text

def _clean_log_line(line: str) -> str | None:
    line = line.strip()
    if not line: return None
    
    # 1. Remove timestamps inside text if repeated
    # (Sometimes logs have double timestamps depending on formatter)
    
    # 2. ANTI-RECURSION FILTER (Hard)
    # Filter out lines that look like someone reading the bot's output
    l_low = line.lower()
    triggers = [
        "заголовок:", "дайджест", "новости сервера", "факт 1", "факт 2", 
        "текст статьи", "смешная цитата", "breaking news", "срочные новости"
    ]
    
    for t in triggers:
        if line.lower().startswith(t) or (len(line) < 50 and t in line.lower()):
            return None # Skip this line completely

    return line

async def generate_news_json(guild_id: int, guild_name: str, days: int = 1) -> dict:
    # --- 1. Collect Logs ---
    collected_lines = []
    user_names_found = set()
    
    def safe_dirname(name: str) -> str:
        keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
        return "".join(c if c in keep else "_" for c in (name or "guild")).strip() or "guild"

    dates = [datetime.datetime.now() - datetime.timedelta(days=i) for i in range(days-1, -1, -1)]
    found_any = False
    
    # Regex to catch names: "Name: Text"
    name_re = re.compile(r"^\s*(.*?):\s")

    for dt in dates:
        date_str = dt.strftime("%Y-%m-%d")
        log_path = os.path.join(LOG_DIR, date_str, safe_dirname(guild_name), f"{date_str}.log")
        
        if os.path.exists(log_path):
            found_any = True
            try:
                with open(log_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        # Skip tech logs
                        if not line or "Sink received" in line or "Processing chunk" in line: continue
                        # Skip timestamp header
                        if len(line) > 11 and line[4] == '-' and line[7] == '-':
                            line = line[11:] 
                        
                        l_low = line.lower()
                        # Filter system events
                        if "joined the channel" in l_low or "left the channel" in l_low or "зашел" in l_low or "вышел" in l_low:
                            continue
                        if ": !" in line or ": /" in line:
                            continue
                        
                        # Apply Cleaning
                        clean_line = _clean_log_line(line)
                        if not clean_line:
                            continue
                            
                        # Extract user
                        m = name_re.match(clean_line)
                        if m:
                            user_names_found.add(m.group(1))

                        collected_lines.append(clean_line)
            except Exception: pass

    if not found_any or len(collected_lines) < 5:
        return {"error": "Слишком мало событий для анализа."}

    # Limit size
    full_text = "\n".join(collected_lines[-600:]) # Last 600 lines

    # --- 2. Build Context (Profiles & Game) ---
    
    # Resolve User IDs from Names (Reverse Lookup via DB is hard without ID in log)
    # We rely on 'display_name' matching what's in DB or Profile Manager cache
    # Ideally, logs should contain IDs, but they are human-readable text.
    # We will fetch ALL profiles for the guild and match by display name map.
    
    # Optimization: Get all profiles once
    # But profile_manager.get_profile needs user_id. 
    # Let's get "Active Users" from ContextManager?
    
    active_ctx = context_manager.get_context(guild_id)
    game_context_str = context_manager.get_ai_context_string(guild_id)
    
    # Try to map names found in logs to profiles
    # We need to scan DB for these names.
    from bot_app.core.state import db
    
    profiles_desc = []
    # Optimization: fetch all profiles for guild once, map by display_name
    try:
        all_profs = await db.get_all_profiles(guild_id) # Returns records
        # We need to fetch the JSON for each? get_all_profiles query returns joined data now?
        # Let's check sql.py. Yes: p.user_id, u.display_name, p.last_updated
        # Wait, it doesn't return the json data in get_all_profiles.
        # Let's just iterate names found and fetch one by one (cached in manager anyway)
        
        for uname in list(user_names_found)[:10]: # Limit to 10 active speakers to save tokens
            uid = await db.get_user_id_by_name(guild_id, uname)
            if uid:
                desc = await profile_manager.get_user_context_string(guild_id, uid, uname)
                profiles_desc.append(desc)
    except Exception as e:
        logger.error(f"Profile fetch error: {e}")
    
    profiles_block = "\n".join(profiles_desc) if profiles_desc else "Профили не найдены."

    # --- 3. Construct System Prompt ---
    
    system_prompt = f"""
Ты — Ведущий новостей игрового сервера. Твоя задача — прочитать лог чата и написать смешную новость.

ВАЖНЫЙ КОНТЕКСТ:
1. {game_context_str}
2. Если игроки говорят непонятные слова, попытайся интерпретировать их через контекст игры (CS2 = стрельба, Dota = магия/линии).
3. Игнорируй бессмысленный шум.

ПРОФИЛИ УЧАСТНИКОВ:
{profiles_block}
Учитывай пол и имена участников! Если профиля нет, считай по контексту.

ПРАВИЛО "АНТИ-РЕКУРСИЯ":
Если в логе кто-то читает текст, похожий на новости (фразы "Заголовок:", "Факт 1", "Новости сервера"), ЭТО НУЖНО ИГНОРИРОВАТЬ.
Это пользователи читают твои старые новости. Не делай новость о том, как кто-то читает новости. Это бред.
Ищи реальные события: споры, победы, смешные оговорки, крики.

ФОРМАТ ОТВЕТА (JSON):
{{
    "headline": "КЛИКБЕЙТНЫЙ ЗАГОЛОВОК",
    "summary": ["Факт 1", "Факт 2"],
    "article": "Текст статьи. Сарказм, ирония. Не бойся подкалывать.",
    "hero": "Ник главного героя (из лога)",
    "quote": "Смешная цитата из лога (или выдуманная в стиле героя)"
}}
Ты отвечаешь ТОЛЬКО валидным JSON.
"""

    user_prompt = f"""
ВОТ ЛОГ ЧАТА:
---
{full_text}
---
Напиши новость.
    """

    logger.info(f"Generating news for {guild_name} with {len(profiles_desc)} profiles.")

    try:
        raw_resp = await ask_ai(user_prompt, system_prompt=system_prompt)
        clean_resp = _extract_json_safe(raw_resp)
        
        if not clean_resp or not clean_resp.strip().startswith("{"):
            logger.warning(f"AI Response Invalid (Skipping JSON parse): {raw_resp[:100]}...")
            return {"error": "AI returned invalid format."}
            
        data = json.loads(clean_resp)
        
        # --- FEED ECHO BUFFER ---
        # We construct the text that users might read aloud
        full_read_text = ""
        if "headline" in data: full_read_text += data["headline"] + ". "
        if "summary" in data and isinstance(data["summary"], list):
            full_read_text += " ".join(data["summary"]) + ". "
        if "article" in data: full_read_text += data["article"]
        
        context_manager.add_bot_output(guild_id, full_read_text)
        
        return data
    except Exception as e:
        logger.error(f"AI News Error: {e}")
        return {"error": f"Ошибка генерации: {e}"}