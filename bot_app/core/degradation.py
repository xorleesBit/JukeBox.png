"""
Graceful Degradation Manager.
Automatically reduces functionality when system is under load.
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot_app.core.metrics import BotMetrics

logger = logging.getLogger(__name__)


class DegradationManager:
    """
    Manages gradual degradation of bot functionality under load.
    Helps maintain stability during high-traffic periods.
    """
    
    # Degradation levels
    LEVEL_NORMAL = 0
    LEVEL_MEDIUM = 1
    LEVEL_HIGH = 2
    LEVEL_CRITICAL = 3
    
    def __init__(self):
        self.degradation_level = self.LEVEL_NORMAL
        self._level_history = []
    
    async def check_and_adjust(self, metrics: "BotMetrics") -> int:
        """
        Check system metrics and adjust degradation level.
        
        Args:
            metrics: Current bot metrics
            
        Returns:
            int: Current degradation level
        """
        previous_level = self.degradation_level
        
        # Determine level based on metrics
        if (metrics.memory_mb > 2048 or 
            metrics.queue_size > 100 or 
            metrics.cpu_percent > 90):
            self.degradation_level = self.LEVEL_CRITICAL
            
        elif (metrics.memory_mb > 1536 or 
              metrics.queue_size > 50 or 
              metrics.cpu_percent > 75):
            self.degradation_level = self.LEVEL_HIGH
            
        elif (metrics.memory_mb > 1024 or 
              metrics.queue_size > 25 or 
              metrics.cpu_percent > 60):
            self.degradation_level = self.LEVEL_MEDIUM
        else:
            self.degradation_level = self.LEVEL_NORMAL
        
        # Log level changes
        if self.degradation_level != previous_level:
            logger.warning(
                f"Degradation level changed: "
                f"{self._level_name(previous_level)} → {self._level_name(self.degradation_level)} "
                f"(Memory: {metrics.memory_mb:.0f}MB, Queue: {metrics.queue_size}, CPU: {metrics.cpu_percent:.1f}%)"
            )
        
        self._level_history.append(self.degradation_level)
        if len(self._level_history) > 100:
            self._level_history.pop(0)
        
        return self.degradation_level
    
    def should_skip_transcription(self) -> bool:
        """
        Should transcription be skipped?
        
        Returns:
            bool: True if should skip
        """
        return self.degradation_level >= self.LEVEL_CRITICAL
    
    def should_reduce_quality(self) -> bool:
        """
        Should audio quality be reduced?
        
        Returns:
            bool: True if should reduce
        """
        return self.degradation_level >= self.LEVEL_HIGH
    
    def get_chunk_duration_multiplier(self) -> float:
        """
        Get chunk duration multiplier based on load.
        Higher multiplier = longer chunks = less processing overhead.
        
        Returns:
            float: Multiplier for chunk duration
        """
        if self.degradation_level >= self.LEVEL_CRITICAL:
            return 3.0  # 3x longer chunks
        elif self.degradation_level >= self.LEVEL_HIGH:
            return 2.0  # 2x longer
        elif self.degradation_level >= self.LEVEL_MEDIUM:
            return 1.5  # 1.5x longer
        return 1.0  # Normal
    
    def get_publish_interval_multiplier(self) -> float:
        """
        Get publish interval multiplier based on load.
        
        Returns:
            float: Multiplier for publish interval
        """
        if self.degradation_level >= self.LEVEL_HIGH:
            return 2.0  # Publish less frequently
        elif self.degradation_level >= self.LEVEL_MEDIUM:
            return 1.5
        return 1.0
    
    def _level_name(self, level: int) -> str:
        """Get human-readable level name."""
        names = {
            self.LEVEL_NORMAL: "NORMAL",
            self.LEVEL_MEDIUM: "MEDIUM",
            self.LEVEL_HIGH: "HIGH",
            self.LEVEL_CRITICAL: "CRITICAL"
        }
        return names.get(level, "UNKNOWN")
    
    def get_status(self) -> dict:
        """
        Get current degradation status.
        
        Returns:
            dict: Status information
        """
        return {
            'level': self.degradation_level,
            'level_name': self._level_name(self.degradation_level),
            'skip_transcription': self.should_skip_transcription(),
            'reduce_quality': self.should_reduce_quality(),
            'chunk_multiplier': self.get_chunk_duration_multiplier(),
            'publish_multiplier': self.get_publish_interval_multiplier()
        }
