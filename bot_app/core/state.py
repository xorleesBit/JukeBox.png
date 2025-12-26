import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot_app.features.voice_logger import VoiceLogger
    from bot_app.core.runtime_settings import RuntimeSettings
    from bot_app.core.app_db import AppDB
    import discord
    import aiohttp

from bot_app.core.dev_manager import dev_manager
from bot_app.core.lru_cache import LRUCacheWithTTL

# Global State Containers
loggers: dict[int, "VoiceLogger"] = {}
settings_cache: LRUCacheWithTTL = LRUCacheWithTTL(max_size=100, ttl_seconds=3600, name="SettingsCache")
user_spam_cooldowns: dict[int, float] = {}
tasks: list[asyncio.Task] = []

# We will inject DB instance here later
db: "AppDB | None" = None
http_session: "aiohttp.ClientSession | None" = None

async def get_settings(guild_id: int) -> "RuntimeSettings":
    """
    Retrieves or creates RuntimeSettings for a guild with LRU caching.
    Ensure 'db' is set before calling this.
    """
    from bot_app.core.runtime_settings import RuntimeSettings  # Local import to avoid circular dependency
    
    # Try cache first
    s = await settings_cache.get(guild_id)
    if s:
        return s
    
    # Create new
    if not db:
        raise RuntimeError("Database not initialized in state")
    
    s = RuntimeSettings(db, guild_id)
    await s.load()
    await settings_cache.set(guild_id, s)
    
    return s

async def cleanup_expired_caches():
    """Periodic cleanup of expired cache entries."""
    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        await settings_cache.clear_expired()

class AppWrapper:
    """
    Interface passed to UI views to interact with the bot's core logic.
    Decouples UI from the main bot file.
    """
    def __init__(self, db_instance: "AppDB"):
        self.db = db_instance
        self.loggers = loggers

    async def get_settings(self, gid: int):
        return await get_settings(gid)

    async def ensure_logger_started(self, interaction: "discord.Interaction"):
        # This will be monkey-patched or imported from voice_control to avoid circular imports
        from bot_app.features.voice_control import ensure_logger_started
        await ensure_logger_started(interaction, self.db)

    async def ensure_logger_stopped(self, gid: int):
        from bot_app.features.voice_control import ensure_logger_stopped
        await ensure_logger_stopped(gid)
