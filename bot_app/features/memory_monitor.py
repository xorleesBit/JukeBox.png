"""
Memory monitoring and alerts for the Discord bot.
Tracks memory usage and triggers cleanup when thresholds are exceeded.
"""
import psutil
import asyncio
import logging
import gc

logger = logging.getLogger(__name__)


class MemoryMonitor:
    """
    Monitors memory usage and triggers alerts/cleanup.
    Designed for multi-server Discord bot deployment.
    """
    
    def __init__(
        self, 
        warning_threshold_mb: int = 1024, 
        critical_threshold_mb: int = 2048,
        check_interval_seconds: int = 60
    ):
        """
        Initialize memory monitor.
        
        Args:
            warning_threshold_mb: Warning threshold in MB
            critical_threshold_mb: Critical threshold in MB
            check_interval_seconds: How often to check memory
        """
        self.warning_threshold = warning_threshold_mb * 1024 * 1024
        self.critical_threshold = critical_threshold_mb * 1024 * 1024
        self.check_interval = check_interval_seconds
        self.process = psutil.Process()
        self.task = None
        
        self._warning_count = 0
        self._critical_count = 0
        
        logger.info(
            f"MemoryMonitor initialized: "
            f"warning={warning_threshold_mb}MB, "
            f"critical={critical_threshold_mb}MB, "
            f"interval={check_interval_seconds}s"
        )
    
    def start(self):
        """Start the monitoring task."""
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._monitor_loop())
            logger.info("MemoryMonitor started")
    
    async def stop(self):
        """Stop the monitoring task."""
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            logger.info("MemoryMonitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                
                mem_info = self.process.memory_info()
                rss = mem_info.rss
                rss_mb = rss / 1024 / 1024
                
                if rss > self.critical_threshold:
                    self._critical_count += 1
                    logger.critical(
                        f"CRITICAL MEMORY: {rss_mb:.1f} MB "
                        f"(threshold: {self.critical_threshold / 1024 / 1024:.1f} MB)"
                    )
                    # Force garbage collection
                    collected = gc.collect()
                    logger.info(f"Emergency GC collected {collected} objects")
                    
                elif rss > self.warning_threshold:
                    self._warning_count += 1
                    logger.warning(
                        f"HIGH MEMORY: {rss_mb:.1f} MB "
                        f"(threshold: {self.warning_threshold / 1024 / 1024:.1f} MB)"
                    )
                else:
                    # Normal operation
                    logger.debug(f"Memory: {rss_mb:.1f} MB")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory monitor error: {e}", exc_info=True)
    
    def get_current_memory_mb(self) -> float:
        """
        Get current memory usage in MB.
        
        Returns:
            float: Current RSS memory in MB
        """
        return self.process.memory_info().rss / 1024 / 1024
    
    def get_stats(self) -> dict:
        """
        Get memory statistics.
        
        Returns:
            dict: Memory usage statistics
        """
        mem_info = self.process.memory_info()
        
        return {
            'rss_mb': mem_info.rss / 1024 / 1024,
            'vms_mb': mem_info.vms / 1024 / 1024,
            'warning_threshold_mb': self.warning_threshold / 1024 / 1024,
            'critical_threshold_mb': self.critical_threshold / 1024 / 1024,
            'warning_count': self._warning_count,
            'critical_count': self._critical_count
        }
