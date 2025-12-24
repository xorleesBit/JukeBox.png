import asyncpg
import time
import json
import logging
from bot_app.core import sql

logger = logging.getLogger("AppDB")

class AppDB:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(self.dsn)
            await self.init_schema()
            logger.info("Connected to PostgreSQL.")
        except Exception as e:
            logger.error(f"Failed to connect to DB: {e}")
            raise

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def init_schema(self):
        async with self.pool.acquire() as conn:
            await conn.execute(sql.INIT_SCHEMA_GUILD_CONFIGS)
            await conn.execute(sql.INIT_SCHEMA_GUILD_PANELS)
            await conn.execute(sql.INIT_SCHEMA_USERS)
            await conn.execute(sql.INIT_SCHEMA_WORD_STATS)
            await conn.execute(sql.INIT_SCHEMA_PRANK_PHRASES)
            await conn.execute(sql.INIT_SCHEMA_USER_PROFILES)
            await conn.execute(sql.INIT_SCHEMA_PERSISTENT_STATE)
            
            # v4.0 New Schemas
            await conn.execute(sql.INIT_SCHEMA_SOUNDPAD)
            await conn.execute(sql.INIT_SCHEMA_REMINDERS)
            await conn.execute(sql.INIT_SCHEMA_AFK)
            await conn.execute(sql.INIT_SCHEMA_INVENTORY)
            await conn.execute(sql.INIT_SCHEMA_BUFFS)
            
            await conn.execute(sql.MIGRATION_V4)
            await conn.execute(sql.INIT_INDEXES)

    # ---- Config ----
    async def get_config(self, guild_id: int) -> dict:
        row = await self.pool.fetchrow(sql.GET_CONFIG, guild_id)
        if row and row['settings']:
            return json.loads(row['settings'])
        return {}

    async def set_config_value(self, guild_id: int, key: str, value):
        cfg = await self.get_config(guild_id)
        cfg[key] = value
        await self.pool.execute(sql.SET_CONFIG, guild_id, json.dumps(cfg))

    # ---- Persistence (Panel & Logs) ----
    async def set_panel(self, guild_id: int, channel_id: int, message_id: int):
        await self.pool.execute(sql.SET_PANEL, guild_id, channel_id, message_id)

    async def get_panel(self, guild_id: int):
        row = await self.pool.fetchrow(sql.GET_PANEL, guild_id)
        if row and row['panel_channel_id']:
            return (row['panel_channel_id'], row['panel_message_id'])
        return None

    async def set_last_log_msg(self, guild_id: int, channel_id: int, message_id: int):
        await self.pool.execute(sql.SET_LAST_LOG, guild_id, channel_id, message_id)

    async def get_last_log_msg(self, guild_id: int):
        row = await self.pool.fetchrow(sql.GET_LAST_LOG, guild_id)
        if row and row['last_log_channel_id']:
            return (row['last_log_channel_id'], row['last_log_message_id'])
        return None

    # ---- Users & XP ----
    async def upsert_user(self, guild_id: int, user_id: int, display_name: str):
        await self.pool.execute(sql.UPSERT_USER, guild_id, user_id, display_name, time.time())

    async def get_user(self, guild_id: int, user_id: int):
        return await self.pool.fetchrow(sql.GET_USER, guild_id, user_id)

    async def get_user_id_by_name(self, guild_id: int, name: str) -> int | None:
        name = name.strip()
        row = await self.pool.fetchrow(sql.GET_USER_ID_BY_NAME_EXACT, guild_id, name)
        if row: return row['user_id']
        
        if len(name) > 2:
            row = await self.pool.fetchrow(sql.GET_USER_ID_BY_NAME_LIKE, guild_id, f"%{name}%")
            if row: return row['user_id']
            
        return None

    async def add_xp_and_words(self, guild_id: int, user_id: int, xp_amount: int, w_text: int, w_audio: int, words_list: list[str] = None):
        coin_reward = int(xp_amount * 0.1)
        await self.pool.execute(sql.ADD_XP_AND_WORDS, guild_id, user_id, xp_amount, coin_reward, w_text, w_audio)
        await self.pool.execute(sql.UPDATE_USER_LEVEL, guild_id, user_id)

        if words_list:
            # Batch optimization for word stats
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # Limit to 50 words per phrase to prevent DB flood
                    for w in words_list[:50]:
                        w = w.lower().strip()[:50]
                        if not w: continue
                        await conn.execute(sql.UPSERT_WORD_STAT, guild_id, user_id, w)

    async def set_user_opt_out(self, guild_id: int, user_id: int, is_opt_out: bool):
        val = 1 if is_opt_out else 0
        await self.pool.execute(sql.SET_USER_OPT_OUT, guild_id, user_id, val)

    async def is_user_opt_out(self, guild_id: int, user_id: int) -> bool:
        val = await self.pool.fetchval(sql.GET_USER_OPT_OUT, guild_id, user_id)
        return val == 1

    # ---- AI Profiles ----
    async def get_profile(self, guild_id: int, user_id: int) -> dict:
        row = await self.pool.fetchrow(sql.GET_PROFILE, guild_id, user_id)
        if row and row['profile_data']:
            return json.loads(row['profile_data'])
        return {}

    async def upsert_profile(self, guild_id: int, user_id: int, data: dict):
        await self.pool.execute(sql.UPSERT_PROFILE, guild_id, user_id, json.dumps(data), time.time())

    async def get_all_profiles(self, guild_id: int):
        return await self.pool.fetch(sql.GET_ALL_PROFILES, guild_id)

    async def append_achievements(self, guild_id: int, user_id: int, new_achs: list):
        current = await self.get_profile(guild_id, user_id)
        existing = current.get('achievements', [])
        if not isinstance(existing, list): existing = []
        
        titles = {a.get('title') for a in existing}
        added_count = 0
        for ach in new_achs:
            if ach.get('title') not in titles:
                existing.append(ach)
                titles.add(ach.get('title'))
                added_count += 1
        
        current['achievements'] = existing
        await self.upsert_profile(guild_id, user_id, current)
        return added_count

    async def reset_all_achievements(self, guild_id: int):
        await self.pool.execute(sql.RESET_ACHIEVEMENTS, guild_id)

    # ---- Economy & Games ----
    async def get_balance(self, guild_id: int, user_id: int) -> int:
        return await self.pool.fetchval("SELECT balance FROM users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id) or 0

    async def update_balance(self, guild_id: int, user_id: int, delta: int):
        await self.pool.execute("UPDATE users SET balance = GREATEST(0, balance + $3) WHERE guild_id=$1 AND user_id=$2", guild_id, user_id, delta)

    async def get_rating(self, guild_id: int, user_id: int) -> int:
        return await self.pool.fetchval("SELECT rating FROM users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id) or 1000

    async def update_rating(self, guild_id: int, user_id: int, delta: int):
        await self.pool.execute("UPDATE users SET rating = rating + $3 WHERE guild_id=$1 AND user_id=$2", guild_id, user_id, delta)

    async def get_top_users(self, guild_id: int, limit=10):
        return await self.pool.fetch("SELECT user_id, xp, level, rating FROM users WHERE guild_id=$1 ORDER BY xp DESC LIMIT $2", guild_id, limit)

    async def get_word_stats(self, guild_id: int, user_id: int, limit=10):
        return await self.pool.fetch("SELECT word, count FROM word_stats WHERE guild_id=$1 AND user_id=$2 ORDER BY count DESC LIMIT $3", guild_id, user_id, limit)

    # ---- Prank Phrases ----
    async def create_phrase_row(self, guild_id: int, user_id: int, created_ts: float, mp3_path: str) -> int:
        return await self.pool.fetchval(sql.INSERT_PHRASE, guild_id, user_id, float(created_ts), mp3_path)

    async def update_phrase_path(self, phrase_id: int, mp3_path: str):
        await self.pool.execute("UPDATE prank_phrases SET mp3_path=$1 WHERE phrase_id=$2", mp3_path, phrase_id)

    async def mark_phrase_transcript(self, phrase_id: int, transcript: str):
        await self.pool.execute("UPDATE prank_phrases SET transcript=$1, transcript_ready=TRUE WHERE phrase_id=$2", transcript, phrase_id)
        
    async def mark_phrase_ready(self, phrase_id: int):
        await self.pool.execute("UPDATE prank_phrases SET transcript_ready=TRUE WHERE phrase_id=$1", phrase_id)

    async def take_pending_phrase(self, guild_id: int):
        return await self.pool.fetchrow(sql.TAKE_PENDING_PHRASE, guild_id)

    async def random_ready_phrase(self, guild_id: int):
        row = await self.pool.fetchrow(sql.RANDOM_READY_PHRASE, guild_id)
        if row:
            return (row['phrase_id'], row['mp3_path'])
        return None
    
    async def get_phrase(self, phrase_id: int):
        return await self.pool.fetchrow("SELECT * FROM prank_phrases WHERE phrase_id=$1", phrase_id)

    async def list_recent_phrases(self, guild_id: int, limit=10):
        return await self.pool.fetch(sql.LIST_RECENT_PHRASES, guild_id, limit)

    async def count_phrases(self, guild_id: int):
        return await self.pool.fetchrow(sql.COUNT_PHRASES, guild_id)

    async def record_play(self, phrase_id: int):
        await self.pool.execute("UPDATE prank_phrases SET used_count=used_count+1 WHERE phrase_id=$1", phrase_id)

    async def delete_phrase(self, phrase_id: int):
        await self.pool.execute("UPDATE prank_phrases SET deleted=TRUE WHERE phrase_id=$1", phrase_id)

    async def delete_all_non_fav_phrases(self, guild_id: int):
        """Safely deletes all phrases for a guild EXCEPT favorites."""
        await self.pool.execute(sql.DELETE_ALL_NON_FAV_PHRASES, guild_id)

    # --- New Methods for Rotation & Favorites ---

    async def set_phrase_favorite(self, phrase_id: int, is_fav: bool):
        await self.pool.execute("UPDATE prank_phrases SET is_favorite=$1 WHERE phrase_id=$2", is_fav, phrase_id)

    async def set_phrase_name(self, phrase_id: int, name: str):
        await self.pool.execute("UPDATE prank_phrases SET name=$1 WHERE phrase_id=$2", name, phrase_id)

    async def get_user_phrase_stats(self, guild_id: int, user_id: int):
        return await self.pool.fetchrow("SELECT COUNT(*) as cnt, MAX(created_ts) as newest FROM prank_phrases WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE", guild_id, user_id)

    async def enforce_phrase_limit(self, guild_id: int, user_id: int, max_per_user: int) -> list[str]:
        if max_per_user <= 0:
            return []
        
        # 1. Fetch cutoff timestamp is handled inside DELETE_OLD_PHRASES query logic? 
        # Actually DELETE_OLD_PHRASES uses LIMIT/OFFSET logic directly in subquery.
        # It says: Delete where ID NOT IN (Top N)
        
        rows = await self.pool.fetch(sql.DELETE_OLD_PHRASES, guild_id, user_id, max_per_user)

        paths = []
        if rows:
            ids = [r['phrase_id'] for r in rows]
            paths = [r['mp3_path'] for r in rows if r['mp3_path']]
            await self.pool.execute(sql.UPDATE_PHRASE_DELETED, ids)
            
        return paths
        
    async def get_user_favorites(self, guild_id: int):
        return await self.pool.fetch(sql.GET_USER_FAVORITES, guild_id)
        
    async def get_all_user_phrases(self, guild_id: int, user_id: int, limit=50):
        return await self.pool.fetch(sql.GET_ALL_USER_PHRASES, guild_id, user_id, limit)

    # ---- Soundpad ----
    async def add_soundpad_sound(self, guild_id: int, user_id: int, name: str, path: str, duration: float):
        return await self.pool.fetchval(sql.INSERT_SOUNDPAD, guild_id, user_id, name, path, time.time(), duration)

    async def get_soundpad_sounds(self, guild_id: int):
        return await self.pool.fetch(sql.GET_SOUNDPAD_SOUNDS, guild_id)

    async def get_sound_by_name(self, guild_id: int, name: str):
        return await self.pool.fetchrow(sql.GET_SOUNDPAD_SOUND_BY_NAME, guild_id, name)

    # ---- Utilities (Reminders, AFK) ----
    async def add_reminder(self, user_id: int, channel_id: int, due_ts: float, text: str):
        return await self.pool.fetchval(sql.INSERT_REMINDER, user_id, channel_id, time.time(), due_ts, text)

    async def get_pending_reminders(self, due_limit_ts: float):
        return await self.pool.fetch(sql.GET_PENDING_REMINDERS, due_limit_ts)

    async def complete_reminder(self, remind_id: int):
        await self.pool.execute(sql.MARK_REMINDER_COMPLETED, remind_id)

    async def set_afk(self, user_id: int, guild_id: int, message: str):
        await self.pool.execute(sql.SET_AFK, user_id, guild_id, message, time.time())

    async def get_afk(self, user_id: int):
        return await self.pool.fetchrow(sql.GET_AFK, user_id)

    async def remove_afk(self, user_id: int):
        await self.pool.execute(sql.DELETE_AFK, user_id)

    # ---- Inventory & Buffs ----
    async def add_item(self, guild_id: int, user_id: int, item_id: str, count: int = 1):
        await self.pool.execute(sql.ADD_ITEM, guild_id, user_id, item_id, count)

    async def remove_item(self, guild_id: int, user_id: int, item_id: str, count: int = 1) -> bool:
        """Returns True if successful, False if not enough items."""
        val = await self.pool.fetchval(sql.REMOVE_ITEM, guild_id, user_id, item_id, count)
        return val is not None

    async def get_inventory(self, guild_id: int, user_id: int):
        return await self.pool.fetch(sql.GET_INVENTORY, guild_id, user_id)

    async def add_buff(self, guild_id: int, user_id: int, buff_id: str, expires_at: float, value: float = 1.0):
        # We need to fetch existing first to stack duration properly?
        # Or we do logic in Python. Let's do UPSERT logic:
        # If exists: New Expire = Old Expire + Duration? 
        # No, SQL UPSERT in sql.py sets to MAX(new, old) currently.
        # Let's handle stacking in Python before calling this.
        await self.pool.execute(sql.UPSERT_BUFF, guild_id, user_id, buff_id, expires_at, value)

    async def get_active_buffs(self, guild_id: int, user_id: int):
        return await self.pool.fetch(sql.GET_ACTIVE_BUFFS, guild_id, user_id, time.time())

    async def get_buff(self, guild_id: int, user_id: int, buff_id: str):
        return await self.pool.fetchrow(sql.GET_SPECIFIC_BUFF, guild_id, user_id, buff_id, time.time())

    async def update_speech_stats(self, guild_id: int, user_id: int, seconds: float):
        await self.pool.execute(sql.UPDATE_SPEECH_STATS, guild_id, user_id, seconds)

    # ---- V4 Economy & Progression ----
    async def claim_daily(self, guild_id: int, user_id: int, amount: int):
        await self.pool.execute(sql.UPDATE_DAILY_CLAIM, guild_id, user_id, time.time(), amount)

    async def add_free_plays(self, guild_id: int, user_id: int, amount: int):
        await self.pool.execute(sql.ADD_FREE_PLAYS, guild_id, user_id, amount)

    async def use_free_play(self, guild_id: int, user_id: int):
        await self.pool.execute(sql.DECREMENT_FREE_PLAYS, guild_id, user_id)
    
    async def get_free_plays(self, guild_id: int, user_id: int) -> int:
        return await self.pool.fetchval("SELECT free_phrase_plays FROM users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id) or 0

    async def reset_xp_keep_level(self, guild_id: int):
        await self.pool.execute(sql.RESET_XP_KEEP_LEVEL, guild_id)
