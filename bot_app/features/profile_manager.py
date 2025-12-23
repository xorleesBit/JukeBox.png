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

    async def _read_logs(self, guild_name: str, limit_chars=30000):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        def safe_dirname(name: str) -> str:
            keep = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
            return "".join(c if c in keep else "_" for c in (name or "guild")).strip() or "guild"
        
        log_path = os.path.join(LOG_DIR, today, safe_dirname(guild_name), f"{today}.log")
        if not os.path.exists(log_path): return None, "Лог файл не найден."
        
        try:
            with open(log_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
                if len(content) > limit_chars:
                    return content[-limit_chars:], None
                return content, None
        except Exception as e:
            return None, str(e)

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
        content, error = await self._read_logs(guild_name)
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
            
            ВЕРНИ JSON ПРОФИЛЯ для этого юзера на основе логов:
            {{
                "interests": [],
                "favorite_phrases": [],
                "games": [],
                "relations": {{}},
                "personality": "..."
            }}
            Оставь старое если нет нового. Текущие данные: {json.dumps(current, ensure_ascii=False)}
            """
            
            try:
                resp = await ask_ai(prompt)
                data = json.loads(self._extract_json(resp))
                
                if 'achievements' in current:
                    data['achievements'] = current['achievements']
                
                await self.db.upsert_profile(self.guild_id, uid, data)
                updated += 1
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Profile AI error {uid}: {e}")

        return f"✅ Обновлено {updated} профилей."

    async def update_achievements(self, guild_name: str):
        content, error = await self._read_logs(guild_name)
        if error: return f"⚠️ {error}"
        
        # 1. Identify active users to provide context
        # We fetch all profiles to get existing achievements
        all_profiles = await self.db.get_all_profiles(self.guild_id)
        
        users_context = []
        for p in all_profiles:
            uid = p['user_id']
            name = p['display_name']
            
            # Optimization: Only include if mentioned in logs
            if name in content or str(uid) in content:
                profile_data = await self.db.get_profile(self.guild_id, uid)
                existing_achs = profile_data.get('achievements', [])
                titles = [a.get('title') for a in existing_achs]
                users_context.append(f"User {name} (ID: {uid}) уже имеет: {titles}")

        context_str = "\n".join(users_context[:20]) # Limit context size
        
        prompt = f"""
        Проанализируй этот лог и выдай НОВЫЕ ачивки (JSON):
        --- ЛОГ ---
        {content[:20000]}
        --- КОНЕЦ ---
        
        СУЩЕСТВУЮЩИЕ АЧИВКИ (НЕ ПОВТОРЯЙ ИХ):
        {context_str}
        
        ЗАДАЧА:
        Верни JSON список НОВЫХ ачивок для пользователей, которые отличились ИМЕННО СЕГОДНЯ.
        
        ТРЕБОВАНИЯ:
        1. Язык: РУССКИЙ.
        2. Формат: СТРОГО JSON (без лишних слов).
        3. Не дублируй банальные вещи ("Зашел в канал"), ищи уникальное.
        
        Формат JSON:
        [
            {{
                "user_id": 12345, 
                "achievements": [
                    {{"title": "Название Ачивки", "desc": "Описание за что", "date": "{datetime.date.today()}"}}
                ]
            }}
        ]
        
        ВАЖНО:
        1. Если юзера нет в базе (не уверен в ID), используй ИМЯ вместо ID.
        2. НЕ пиши ничего кроме JSON.
        """
        
        try:
            resp = await ask_ai(prompt, system_prompt="Ты сервер, отвечающий строго JSON массивом на русском языке.")
            logger.info(f"[RAW AI ACHS]: {resp}") 
            
            if not resp or resp.startswith("⚠️"):
                return f"AI Error: {resp}"

            try:
                clean_json = self._extract_json(resp)
                data = json.loads(clean_json)
            except json.JSONDecodeError:
                return f"⚠️ Ошибка JSON от AI. См. логи."

            count = 0
            if isinstance(data, list):
                for item in data:
                    uid = item.get('user_id')
                    # Resolve Name -> ID if needed
                    if isinstance(uid, str) and not uid.isdigit():
                        uid = await self.db.get_user_id_by_name(self.guild_id, uid)
                    
                    new_achs = item.get('achievements', [])
                    if uid and new_achs:
                        try:
                            uid = int(uid)
                            c = await self.db.append_achievements(self.guild_id, uid, new_achs)
                            count += c
                        except: pass
            
            return f"🏆 Выдано {count} новых ачивок."
        except Exception as e:
            return f"❌ Ошибка: {e}"