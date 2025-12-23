from dataclasses import dataclass

@dataclass
class Item:
    id: str
    name: str
    description: str
    price: int
    buff_id: str  # ID used in active_buffs table
    duration_sec: int
    value: float = 1.0 # Multiplier or bool flag (1.0)
    emoji: str = "📦"

ITEMS = {
    "xp_potion": Item(
        id="xp_potion",
        name="Зелье Мудрости",
        description="+50% опыта в войсе (1 час)",
        price=200,
        buff_id="xp_boost",
        duration_sec=3600,
        value=1.5,
        emoji="🧪"
    ),
    "ghost_cloak": Item(
        id="ghost_cloak",
        name="Плащ Теней",
        description="Вас не записывают в логи (12 часов)",
        price=1000,
        buff_id="ghost_mode",
        duration_sec=43200,
        value=1.0,
        emoji="🕶️"
    ),
    "anti_roast": Item(
        id="anti_roast",
        name="Зеркало Отражения",
        description="Иммунитет к прожарке !roast (24 часа)",
        price=500,
        buff_id="anti_roast",
        duration_sec=86400,
        value=1.0,
        emoji="🛡️"
    ),
    "coin_magnet": Item(
        id="coin_magnet",
        name="Магнит Монет",
        description="Удваивает награду за !daily (2 дня)",
        price=300,
        buff_id="daily_boost",
        duration_sec=172800,
        value=2.0,
        emoji="💎"
    ),
    "sound_pass": Item(
        id="sound_pass",
        name="Абонемент Саундпада",
        description="Бесплатная загрузка звуков (7 дней)",
        price=2000,
        buff_id="sound_free",
        duration_sec=604800,
        value=1.0,
        emoji="🎫"
    )
}

def get_item(item_id: str) -> Item | None:
    return ITEMS.get(item_id)
