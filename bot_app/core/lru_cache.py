"""
LRU Cache with TTL support for runtime settings and other cached data.
"""
import time
import asyncio
import logging
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LRUCacheWithTTL:
    """
    LRU (Least Recently Used) cache with Time-To-Live expiration.
    Prevents memory leaks from unlimited caching.
    """
    
    def __init__(self, max_size: int = 100, ttl_seconds: float = 3600, name: str = "Cache"):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of items in cache
            ttl_seconds: Time to live for cached items in seconds
            name: Name for logging purposes
        """
        self.max_size = max_size
        self.ttl = ttl_seconds
        self.name = name
        self.cache: OrderedDict = OrderedDict()
        self.timestamps: dict = {}
        self._lock = asyncio.Lock()
        
        logger.info(
            f"LRUCache '{name}' initialized: "
            f"max_size={max_size}, ttl={ttl_seconds}s"
        )
    
    async def get(self, key: Any) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        async with self._lock:
            if key not in self.cache:
                return None
            
            # Check TTL
            if time.time() - self.timestamps.get(key, 0) > self.ttl:
                self.cache.pop(key, None)
                self.timestamps.pop(key, None)
                logger.debug(f"LRUCache '{self.name}': key '{key}' expired")
                return None
            
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            return self.cache[key]
    
    async def set(self, key: Any, value: Any):
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        async with self._lock:
            if key in self.cache:
                # Update existing
                self.cache.move_to_end(key)
            else:
                # Add new
                self.cache[key] = value
                
                # Evict oldest if size exceeded
                if len(self.cache) > self.max_size:
                    oldest_key = next(iter(self.cache))
                    self.cache.pop(oldest_key)
                    self.timestamps.pop(oldest_key, None)
                    logger.debug(
                        f"LRUCache '{self.name}': evicted '{oldest_key}' (size limit)"
                    )
            
            self.timestamps[key] = time.time()
    
    async def delete(self, key: Any):
        """
        Delete value from cache.
        
        Args:
            key: Cache key
        """
        async with self._lock:
            self.cache.pop(key, None)
            self.timestamps.pop(key, None)
    
    async def clear_expired(self):
        """Clear all expired entries from cache."""
        async with self._lock:
            now = time.time()
            expired = [k for k, ts in self.timestamps.items() if now - ts > self.ttl]
            
            for k in expired:
                self.cache.pop(k, None)
                self.timestamps.pop(k, None)
            
            if expired:
                logger.info(
                    f"LRUCache '{self.name}': cleared {len(expired)} expired entries"
                )
    
    def get_stats(self) -> dict:
        """
        Get cache statistics.
        
        Returns:
            dict: Statistics about cache usage
        """
        return {
            'name': self.name,
            'size': len(self.cache),
            'max_size': self.max_size,
            'utilization': len(self.cache) / self.max_size if self.max_size > 0 else 0,
            'ttl_seconds': self.ttl
        }
