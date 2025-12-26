"""
HTTP Session Pool with connection limits and timeouts.
Manages aiohttp sessions for multiple Discord servers.
"""
import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HTTPSessionPool:
    """
    Manages a shared HTTP session pool with connection limits.
    Designed to handle multiple Discord servers efficiently.
    """
    
    def __init__(
        self, 
        max_connections_per_host: int = 10, 
        total_connections: int = 100,
        timeout_total: int = 60,
        timeout_connect: int = 10,
        timeout_sock_read: int = 30
    ):
        """
        Initialize HTTP session pool.
        
        Args:
            max_connections_per_host: Max connections per host
            total_connections: Total max connections across all hosts
            timeout_total: Total timeout in seconds
            timeout_connect: Connection timeout in seconds
            timeout_sock_read: Socket read timeout in seconds
        """
        # Store config for lazy initialization
        self._max_connections_per_host = max_connections_per_host
        self._total_connections = total_connections
        self._timeout_total = timeout_total
        self._timeout_connect = timeout_connect
        self._timeout_sock_read = timeout_sock_read
        
        # Will be created when event loop is running
        self._connector: Optional[aiohttp.TCPConnector] = None
        self._session: Optional[aiohttp.ClientSession] = None
        
        logger.info(
            f"HTTPSessionPool configured: "
            f"total={total_connections}, per_host={max_connections_per_host}"
        )
    
    async def get_session(self) -> aiohttp.ClientSession:
        """
        Get or create the shared HTTP session.
        Lazy initializes connector when event loop is available.
        
        Returns:
            aiohttp.ClientSession: The shared session
        """
        # Lazy create connector (requires event loop)
        if self._connector is None:
            self._connector = aiohttp.TCPConnector(
                limit=self._total_connections,
                limit_per_host=self._max_connections_per_host,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
                force_close=False  # Reuse connections
            )
            logger.info("HTTP connector created")
        
        # Create session if needed
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self._timeout_total,
                connect=self._timeout_connect,
                sock_read=self._timeout_sock_read
            )
            
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                timeout=timeout,
                connector_owner=False  # Don't close connector when session closes
            )
            logger.info("HTTP session created")
        
        return self._session
    
    async def close(self):
        """Close the session and connector."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("HTTP session closed")
        
        if self._connector:
            await self._connector.close()
            logger.info("HTTP connector closed")
    
    def get_stats(self) -> dict:
        """
        Get connection pool statistics.
        
        Returns:
            dict: Statistics about the connection pool
        """
        return {
            'connector_limit': self._connector.limit,
            'connector_limit_per_host': self._connector.limit_per_host,
        }
