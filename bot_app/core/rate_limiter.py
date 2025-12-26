"""
Rate limiter for API calls (STT, AI, etc.).
Implements token bucket algorithm for rate limiting.
"""
import asyncio
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)


class APIRateLimiter:
    """
    Rate limiter using sliding window algorithm.
    Prevents API quota exhaustion for multiple Discord servers.
    """
    
    def __init__(self, max_requests: int, time_window: float, name: str = "API"):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
            name: Name for logging purposes
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.name = name
        self.requests = deque()
        self._lock = asyncio.Lock()
        
        logger.info(
            f"RateLimiter '{name}' initialized: "
            f"{max_requests} requests per {time_window}s"
        )
    
    async def acquire(self):
        """
        Acquire permission to make an API call.
        Blocks if rate limit is exceeded.
        """
        async with self._lock:
            now = time.time()
            
            # Remove old requests outside the time window
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()
            
            # If limit exceeded, wait
            if len(self.requests) >= self.max_requests:
                sleep_time = self.time_window - (now - self.requests[0])
                if sleep_time > 0:
                    logger.warning(
                        f"RateLimiter '{self.name}' throttling: "
                        f"sleeping {sleep_time:.2f}s"
                    )
                    await asyncio.sleep(sleep_time)
                    return await self.acquire()
            
            # Record this request
            self.requests.append(now)
    
    def get_stats(self) -> dict:
        """
        Get current rate limiter statistics.
        
        Returns:
            dict: Statistics including current usage
        """
        now = time.time()
        recent = sum(1 for t in self.requests if t > now - self.time_window)
        
        return {
            'name': self.name,
            'current_requests': recent,
            'max_requests': self.max_requests,
            'time_window': self.time_window,
            'utilization': recent / self.max_requests if self.max_requests > 0 else 0
        }
