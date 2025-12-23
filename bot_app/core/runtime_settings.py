import asyncio

class RuntimeSettings:
    def __init__(self, db, guild_id: int):
        self.db = db
        self.guild_id = int(guild_id)
        self._cache = {}
        self._loaded = False

    async def load(self):
        if self._loaded:
            return
        self._cache = await self.db.get_config(self.guild_id)
        self._loaded = True

    def get_int(self, key: str, default: int = 0) -> int:
        val = self._cache.get(key)
        if val is not None:
            try:
                return int(val)
            except:
                pass
        return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        val = self._cache.get(key)
        if val is not None:
            try:
                return float(val)
            except:
                pass
        return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self._cache.get(key)
        if val is not None:
            return bool(val)
        return default

    def set_int(self, key: str, value: int):
        self._cache[key] = int(value)
        asyncio.create_task(self.db.set_config_value(self.guild_id, key, int(value)))

    def set_float(self, key: str, value: float):
        self._cache[key] = float(value)
        asyncio.create_task(self.db.set_config_value(self.guild_id, key, float(value)))

    def set_bool(self, key: str, value: bool):
        self._cache[key] = bool(value)
        asyncio.create_task(self.db.set_config_value(self.guild_id, key, bool(value)))