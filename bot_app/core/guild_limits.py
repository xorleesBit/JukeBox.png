"""
Per-Guild Resource Limits Manager.
Controls resource allocation per Discord server.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GuildLimits:
    """Resource limits for a guild."""
    max_chunk_queue_size: int = 10
    max_concurrent_transcriptions: int = 3
    max_memory_mb: int = 512


class GuildResourceManager:
    """
    Manages resource allocation per guild.
    Prevents any single guild from monopolizing bot resources.
    """
    
    def __init__(self):
        self.limits: dict[int, GuildLimits] = {}
        self.current_usage: dict[int, dict] = {}
    
    def set_limits(self, guild_id: int, limits: GuildLimits):
        """
        Set resource limits for a guild.
        
        Args:
            guild_id: Guild ID
            limits: Resource limits to apply
        """
        self.limits[guild_id] = limits
        logger.info(f"Limits set for guild {guild_id}: {limits}")
    
    def get_limits(self, guild_id: int) -> GuildLimits:
        """
        Get limits for a guild (or default).
        
        Args:
            guild_id: Guild ID
            
        Returns:
            GuildLimits for the guild
        """
        return self.limits.get(guild_id, GuildLimits())
    
    async def can_enqueue_chunk(self, guild_id: int) -> bool:
        """
        Check if guild can enqueue another chunk.
        
        Args:
            guild_id: Guild ID
            
        Returns:
            bool: True if can enqueue
        """
        usage = self.current_usage.get(guild_id, {})
        limits = self.get_limits(guild_id)
        
        current_queue = usage.get('queue_size', 0)
        can_enqueue = current_queue < limits.max_chunk_queue_size
        
        if not can_enqueue:
            logger.warning(
                f"Guild {guild_id} queue limit reached: "
                f"{current_queue}/{limits.max_chunk_queue_size}"
            )
        
        return can_enqueue
    
    async def acquire_transcription_slot(self, guild_id: int) -> bool:
        """
        Acquire a transcription slot for a guild.
        
        Args:
            guild_id: Guild ID
            
        Returns:
            bool: True if acquired
        """
        usage = self.current_usage.setdefault(guild_id, {})
        limits = self.get_limits(guild_id)
        
        current_transcriptions = usage.get('transcriptions', 0)
        
        if current_transcriptions >= limits.max_concurrent_transcriptions:
            logger.warning(
                f"Guild {guild_id} transcription limit reached: "
                f"{current_transcriptions}/{limits.max_concurrent_transcriptions}"
            )
            return False
        
        usage['transcriptions'] = current_transcriptions + 1
        return True
    
    async def release_transcription_slot(self, guild_id: int):
        """
        Release a transcription slot.
        
        Args:
            guild_id: Guild ID
        """
        usage = self.current_usage.get(guild_id, {})
        usage['transcriptions'] = max(0, usage.get('transcriptions', 0) - 1)
    
    def update_queue_size(self, guild_id: int, size: int):
        """
        Update queue size for a guild.
        
        Args:
            guild_id: Guild ID
            size: Current queue size
        """
        usage = self.current_usage.setdefault(guild_id, {})
        usage['queue_size'] = size
    
    def get_stats(self, guild_id: int) -> dict:
        """
        Get resource usage stats for a guild.
        
        Args:
            guild_id: Guild ID
            
        Returns:
            dict: Usage statistics
        """
        usage = self.current_usage.get(guild_id, {})
        limits = self.get_limits(guild_id)
        
        return {
            'guild_id': guild_id,
            'queue_size': usage.get('queue_size', 0),
            'queue_limit': limits.max_chunk_queue_size,
            'transcriptions': usage.get('transcriptions', 0),
            'transcription_limit': limits.max_concurrent_transcriptions
        }
