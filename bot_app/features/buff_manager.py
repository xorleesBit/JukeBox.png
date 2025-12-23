import time
from bot_app.core.items_registry import ITEMS, Item

class BuffManager:
    def __init__(self, db):
        self.db = db

    async def use_item(self, guild_id: int, user_id: int, item_id: str) -> tuple[bool, str]:
        """
        Consumes item from inventory and applies buff.
        Returns (Success, Message).
        """
        item = ITEMS.get(item_id)
        if not item:
            return False, "Предмет не найден."
        
        # 1. Remove from inventory
        success = await self.db.remove_item(guild_id, user_id, item_id, 1)
        if not success:
            return False, "У вас нет этого предмета."
        
        # 2. Calculate Expiration
        # Check current buff to stack duration
        current = await self.db.get_buff(guild_id, user_id, item.buff_id)
        
        now = time.time()
        start_time = now
        
        if current:
            # If already active, add to existing expiry
            # But ensure we don't stack past reasonable limits (e.g. 30 days)
            start_time = max(now, current['expires_at'])
        
        new_expire = start_time + item.duration_sec
        
        # 3. Apply
        await self.db.add_buff(guild_id, user_id, item.buff_id, new_expire, item.value)
        
        return True, f"Использован {item.emoji} **{item.name}**! Эффект продлен до <t:{int(new_expire)}:R>."

    async def has_buff(self, guild_id: int, user_id: int, buff_id: str) -> bool:
        b = await self.db.get_buff(guild_id, user_id, buff_id)
        return bool(b)

    async def get_buff_value(self, guild_id: int, user_id: int, buff_id: str, default=1.0) -> float:
        b = await self.db.get_buff(guild_id, user_id, buff_id)
        if b:
            return float(b['value'])
        return default
