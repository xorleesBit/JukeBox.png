import logging
import json
import time
import discord
from bot_app.integrations.ai_client import ask_ai

logger = logging.getLogger(__name__)

class AchievementsManager:
    def __init__(self, db):
        self.db = db

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
