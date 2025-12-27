import logging
import discord
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)

class UserProfile(TypedDict):
    real_name: Optional[str]
    gender: str  # "male", "female", "neutral"
    bio: str
    game_aliases: list[str]
    toxic_level: int # 0-10, for flavor
    custom_prompt: str # User-specific instructions for AI

DEFAULT_PROFILE: UserProfile = {
    "real_name": None,
    "gender": "neutral",
    "bio": "",
    "game_aliases": [],
    "toxic_level": 5,
    "custom_prompt": ""
}

class ProfileManager:
    def __init__(self, db):
        self.db = db
        self._cache = {} # Simple in-memory cache, maybe LRU later if needed

    async def get_profile(self, guild_id: int, user_id: int) -> UserProfile:
        """Fetches profile from DB or returns default."""
        cache_key = f"{guild_id}:{user_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = await self.db.get_profile(guild_id, user_id)
        if not data:
            profile = DEFAULT_PROFILE.copy()
        else:
            profile = DEFAULT_PROFILE.copy()
            profile.update(data) # Merge with defaults
            
        self._cache[cache_key] = profile
        return profile

    async def update_profile(self, guild_id: int, user_id: int, updates: dict):
        """Updates specific fields in the profile."""
        current = await self.get_profile(guild_id, user_id)
        current.update(updates)
        
        await self.db.upsert_profile(guild_id, user_id, current)
        
        # Update cache
        self._cache[f"{guild_id}:{user_id}"] = current
        logger.info(f"Updated profile for {user_id} in {guild_id}: {updates.keys()}")

    async def get_user_context_string(self, guild_id: int, user_id: int, display_name: str) -> str:
        """Returns a string description of the user for AI Prompt."""
        p = await self.get_profile(guild_id, user_id)
        
        name = p['real_name'] or display_name
        gender_map = {"male": "мужчина", "female": "женщина", "neutral": "игрок"}
        gender_str = gender_map.get(p['gender'], "игрок")
        
        desc = f"- {display_name} (Имя: {name}, Пол: {gender_str})"
        if p['bio']:
            desc += f". О себе: {p['bio']}"
        if p['game_aliases']:
            desc += f". Клички: {', '.join(p['game_aliases'])}"
            
        return desc
