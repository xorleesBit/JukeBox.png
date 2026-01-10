"""
Bot metrics collection and reporting.
Provides insights into bot performance and resource usage.
"""
import psutil
import logging
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

logger = logging.getLogger(__name__)


@dataclass
class BotMetrics:
    """Metrics data class for bot monitoring."""
    active_guilds: int = 0
    active_loggers: int = 0
    queue_size: int = 0
    db_pool_size: int = 0
    db_pool_free: int = 0
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    
    # STT metrics
    stt_requests_total: int = 0
    stt_requests_failed: int = 0
    stt_avg_duration_sec: float = 0.0


async def collect_metrics(bot) -> BotMetrics:
    """
    Collect current bot metrics.
    
    Args:
        bot: Discord bot instance
        
    Returns:
        BotMetrics: Current metrics snapshot
    """
    metrics = BotMetrics()
    
    # Bot basic info
    metrics.active_guilds = len(bot.guilds)
    
    if hasattr(bot, 'loggers'):
        metrics.active_loggers = len(bot.loggers)
    
    # Database pool
    if hasattr(bot, 'db') and bot.db.pool:
        try:
            metrics.db_pool_size = bot.db.pool.get_size()
            metrics.db_pool_free = bot.db.pool.get_idle_size()
        except Exception as e:
            logger.debug(f"Could not get DB pool stats: {e}")
    
    # System resources
    try:
        process = psutil.Process()
        metrics.memory_mb = process.memory_info().rss / 1024 / 1024
        # Non-blocking CPU check (returns usage since last call)
        metrics.cpu_percent = process.cpu_percent(interval=None)
    except Exception as e:
        logger.debug(f"Could not get system stats: {e}")
    
    # Queue size across all loggers
    total_queue = 0
    if hasattr(bot, 'loggers'):
        for logger_instance in bot.loggers.values():
            if hasattr(logger_instance, 'processor'):
                try:
                    total_queue += logger_instance.processor.queue_size()
                except Exception:
                    pass
    metrics.queue_size = total_queue
    
    return metrics


def format_metrics(metrics: BotMetrics) -> str:
    """
    Format metrics as human-readable string.
    
    Args:
        metrics: Metrics to format
        
    Returns:
        str: Formatted metrics string
    """
    lines = [
        f"Guilds: {metrics.active_guilds}",
        f"Active Loggers: {metrics.active_loggers}",
        f"Queue Size: {metrics.queue_size}",
        f"Memory: {metrics.memory_mb:.1f} MB",
        f"CPU: {metrics.cpu_percent:.1f}%",
    ]
    
    if metrics.db_pool_size > 0:
        lines.append(
            f"DB Pool: {metrics.db_pool_size - metrics.db_pool_free}/{metrics.db_pool_size} used"
        )
    
    return " | ".join(lines)
