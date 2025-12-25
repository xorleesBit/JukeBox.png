import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot_app.features.voice_logger import VoiceLogger
    from bot_app.core.runtime_settings import RuntimeSettings
    from bot_app.core.app_db import AppDB
    import discord
    import aiohttp

from bot_app.core.dev_manager import dev_manager

# Global State Containers
loggers: dict[int, "VoiceLogger"] = {}
settings_cache: dict[int, "RuntimeSettings"] = {}
user_spam_cooldowns: dict[int, float] = {}
tasks: list[asyncio.Task] = []

# We will inject DB instance here later
db: "AppDB | None" = None
http_session: "aiohttp.ClientSession | None" = None

def get_settings(guild_id: int) -> "RuntimeSettings":
    """
    Retrieves or creates RuntimeSettings for a guild.
    Ensure 'db' is set before calling this.
    """
    from bot_app.core.runtime_settings import RuntimeSettings  # Local import to avoid circular dependency
    
    s = settings_cache.get(guild_id)
    if not s:
        if not db:
            raise RuntimeError("Database not initialized in state")
        s = RuntimeSettings(db, guild_id)
        asyncio.create_task(s.load())
        settings_cache[guild_id] = s
    return s

class AppWrapper:
    """
    Interface passed to UI views to interact with the bot's core logic.
    Decouples UI from the main bot file.
    """
    def __init__(self, db_instance: "AppDB"):
        self.db = db_instance
        self.loggers = loggers

    def get_settings(self, gid: int):
        return get_settings(gid)

    async def ensure_logger_started(self, interaction: "discord.Interaction"):
        # This will be monkey-patched or imported from voice_control to avoid circular imports
        from bot_app.features.voice_control import ensure_logger_started
        await ensure_logger_started(interaction, self.db)

    async def ensure_logger_stopped(self, gid: int):
        from bot_app.features.voice_control import ensure_logger_stopped
        await ensure_logger_stopped(gid)
