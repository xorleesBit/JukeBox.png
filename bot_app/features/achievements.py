import logging
import json
import time
import discord
from bot_app.integrations.ai_client import ask_ai

logger = logging.getLogger(__name__)

class AchievementsManager:
    def __init__(self, db):
        self.db = db

    async def update_achievements(self, guild_id: int, guild_name: str, days: int = 1) -> str:
        """
        Generates and SAVES achievements to user profiles.
        """
        top_users = await self.db.get_top_users(guild_id, limit=5)
        if not top_users:
            return "Нет данных для генерации достижений."
            
        users_info = []
        user_id_map = {} # To map display name back to ID
        
        for r in top_users:
            u_data = await self.db.get_user(guild_id, r['user_id'])
            name = u_data['display_name'] if u_data else f"User{r['user_id']}"
            user_id_map[name.lower()] = r['user_id']
            
            words = await self.db.get_word_stats(guild_id, r['user_id'], limit=3)
            top_words = ", ".join([w['word'] for w in words])
            users_info.append(f"- {name}: LVL {r['level']}, XP {r['xp']}, Топ слова: [{top_words}]")

        prompt = (
            f"Сервер: {guild_name}.\n"
            f"Период: {days} дн.\n"
            f"Пользователи:\n" + "\n".join(users_info) + "\n\n"
            "Придумай по одной уникальной ачивке для каждого. Используй юмор. "
            "ОБЯЗАТЕЛЬНО используй формат для каждой строки:\n"
            "USER_NAME | TITLE | DESCRIPTION\n"
        )

        raw_response = await ask_ai(prompt, system_prompt="Ты — раздатчик достижений. Отвечай СТРОГО в формате: Имя | Название | Описание")
        
        lines = raw_response.strip().split("\n")
        awarded_count = 0
        
        from bot_app.core.state import profile_manager
        
        for line in lines:
            if "|" not in line: continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3: continue
            
            uname, title, desc = parts[0], parts[1], parts[2]
            
            # Find user ID
            uid = user_id_map.get(uname.lower())
            if not uid:
                # Try fuzzy/substring match
                for name, id_val in user_id_map.items():
                    if name in uname.lower() or uname.lower() in name:
                        uid = id_val
                        break
            
            if uid and profile_manager:
                p = await profile_manager.get_profile(guild_id, uid)
                if 'achievements' not in p: p['achievements'] = []
                
                # Add new achievement
                p['achievements'].append({
                    "title": title,
                    "desc": desc,
                    "date": time.strftime("%Y-%m-%d")
                })
                
                # Keep only last 50
                p['achievements'] = p['achievements'][-50:]
                
                await profile_manager.update_profile(guild_id, uid, {"achievements": p['achievements']})
                awarded_count += 1
                
        return f"🏆 Раздача завершена! Выдано достижений: {awarded_count}.\n\n{raw_response[:500]}..."

    async def generate_achievements(self, guild_id: int, guild_name: str) -> str:
        # 1. Gather stats
        # We need generic stats: top talkers, most phrases, etc.
        top_users = await self.db.get_top_users(guild_id, limit=5)
        
        # Prepare context for AI
        users_info = []
        for r in top_users:
            # We need names
            u_data = await self.db.get_user(guild_id, r['user_id'])
            name = u_data['display_name'] if u_data else f"User{r['user_id']}"
            
            # Get word stats for flavor
            words = await self.db.get_word_stats(guild_id, r['user_id'], limit=3)
            top_words = ", ".join([w['word'] for w in words])
            
            users_info.append(f"- {name}: LVL {r['level']}, XP {r['xp']}, Топ слова: [{top_words}]")

        if not users_info:
            return "Нет данных для генерации достижений."

        prompt = (
            f"Сервер: {guild_name}.\n"
            f"Пользователи:\n" + "\n".join(users_info) + "\n\n"
            "Задача: Придумай смешные, саркастические ачивки (медали) для этих пользователей на основе их статистики. "
            "Используй черный юмор, но без оскорблений. "
            "Формат: **Пользователь** — 🏅 *Название ачивки*: Описание."
        )

        response = await ask_ai(prompt, system_prompt="Ты — саркастичный бот-раздатчик достижений.")
        return response
