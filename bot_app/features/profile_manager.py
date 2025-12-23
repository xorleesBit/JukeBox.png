import os
import json
import re
import datetime
import asyncio
import logging
from bot_app.core.config import LOG_DIR
from bot_app.integrations.ai_client import ask_ai

logger = logging.getLogger(__name__)

class ProfileManager:
    def __init__(self, db, guild_id: int):
        self.db = db
        self.guild_id = int(guild_id)

    async def _read_logs(self, guild_name: str, days: int = 1, limit_chars=40000):
        def safe_dirname(name: str) -> str:
            keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
            return "".join(c if c in keep else "_" for c in (name or "guild")).strip() or "guild"

        collected = []
        found = False
        
        dates = [datetime.datetime.now() - datetime.timedelta(days=i) for i in range(days-1, -1, -1)]
        
        for dt in dates:
            date_str = dt.strftime("%Y-%m-%d")
            log_path = os.path.join(LOG_DIR, date_str, safe_dirname(guild_name), f"{date_str}.log")
            
            if os.path.exists(log_path):
                found = True
                try:
                    with open(log_path, "r", encoding="utf-8-sig") as f:
                        # Read entire file, but optimize
                        content = f.read()
                        if "Sink received" not in content: # Quick check if it's raw
                             # Simple cleanup
                             lines = [l.strip() for l in content.splitlines() if l.strip() and "Sink received" not in l]
                             collected.append(f"--- ДАТА: {date_str} ---\n" + "\n".join(lines[-1000:])) # Take last 1000 lines
                except Exception: pass
        
        if not found:
            return None, "Логи не найдены."
            
        full = "\n".join(collected)
        if len(full) > limit_chars:
            full = full[-limit_chars:]
            
        return full, None

    def _extract_json(self, text: str) -> str:
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        start_brace = text.find("{")
        start_bracket = text.find("[")
        
        start = -1
        if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
            start = start_brace
            end = text.rfind("}")
        elif start_bracket != -1:
            start = start_bracket
            end = text.rfind("]")
        else:
            return text 

        if start != -1 and end != -1:
            return text[start:end+1]
        return text

    async def run_analysis(self, guild_name: str):
        # Always analyze just 1 day for profiles to keep it fast, 
        # unless we want "deep analysis" (maybe later)
        content, error = await self._read_logs(guild_name, days=1, limit_chars=20000)
        if error: return f"⚠️ {error}"
        
        db_users = await self.db.get_all_profiles(self.guild_id)
        if not db_users: return "Нет профилей в БД."
        
        updated = 0
        for r in db_users:
            uid = r['user_id']
            name = r['display_name']
            
            if name not in content and str(uid) not in content:
                continue

            current = await self.db.get_profile(self.guild_id, uid)
            
            prompt = f"""
            Ты - AI Аналитик.
            ПОЛЬЗОВАТЕЛЬ: {name} (ID: {uid})
            
            ВЕРНИ JSON ПРОФИЛЯ:
            {{
                "interests": [],
                "favorite_phrases": [],
                "games": [],
                "relations": {{}},
                "personality": "..."
            }}
            Оставь старое если нет нового. Текущие: {json.dumps(current, ensure_ascii=False)}
            """
            
            try:
                resp = await ask_ai(prompt)
                data = json.loads(self._extract_json(resp))
                if 'achievements' in current: data['achievements'] = current['achievements']
                await self.db.upsert_profile(self.guild_id, uid, data)
                updated += 1
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Profile AI error {uid}: {e}")

        return f"✅ Обновлено {updated} профилей."

    async def update_achievements(self, guild_name: str, days: int = 1):
        # Limit context to avoid overload (25k chars is safe for most models)
        limit = 25000 if days > 1 else 15000
        content, error = await self._read_logs(guild_name, days=days, limit_chars=limit)
        if error: return f"⚠️ {error}"
        
        all_profiles = await self.db.get_all_profiles(self.guild_id)
        users_context = []
        for p in all_profiles:
            uid = p['user_id']
            if p['display_name'] in content or str(uid) in content:
                existing = (await self.db.get_profile(self.guild_id, uid)).get('achievements', [])
                titles = [a.get('title') for a in existing]
                users_context.append(f"User {p['display_name']} (ID: {uid}): {titles}")

        context_str = "\n".join(users_context[:30])
        period = "сегодня" if days == 1 else f"последние {days} дней"
        
        prompt = f"""
        Проанализируй логи за {period} и выдай НОВЫЕ ачивки (JSON):
        --- ЛОГ ---
        {content}
        --- КОНЕЦ ---
        
        СУЩЕСТВУЮЩИЕ АЧИВКИ (НЕ ДУБЛИРУЙ):
        {context_str}
        
        ЗАДАЧА:
        Верни JSON список НОВЫХ ачивок.
        
        ТРЕБОВАНИЯ:
        1. Язык: РУССКИЙ.
        2. Формат: СТРОГО JSON.
        
        Формат JSON:
        [
            {{
                "user_id": 12345, 
                "achievements": [
                    {{"title": "Название", "desc": "Описание", "date": "{datetime.date.today()}"}}
                ]
            }}
        ]
        """
        
        try:
            resp = await ask_ai(prompt, system_prompt="Ты сервер, отвечающий строго JSON.")
            logger.info(f"[RAW AI ACHS {days}d]: {resp}") 
            
            if not resp or resp.startswith("⚠️"): return f"AI Error: {resp}"

            try:
                clean_json = self._extract_json(resp)
                data = json.loads(clean_json)
            except json.JSONDecodeError:
                return f"⚠️ Ошибка JSON от AI."

            count = 0
            if isinstance(data, list):
                for item in data:
                    uid = item.get('user_id')
                    if isinstance(uid, str) and not uid.isdigit():
                        uid = await self.db.get_user_id_by_name(self.guild_id, uid)
                    
                    new_achs = item.get('achievements', [])
                    if uid and new_achs:
                        try:
                            c = await self.db.append_achievements(self.guild_id, int(uid), new_achs)
                            count += c
                        except: pass
            
            return f"🏆 Выдано {count} новых ачивок (за {days} дн)."
        except Exception as e:
            return f"❌ Ошибка: {e}"