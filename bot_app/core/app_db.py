import asyncpg
import time
import json
import logging

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
            # Tables
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_configs (
                    guild_id BIGINT PRIMARY KEY,
                    settings JSONB DEFAULT '{}'::jsonb
                );
                CREATE TABLE IF NOT EXISTS guild_panels (
                    guild_id BIGINT PRIMARY KEY,
                    channel_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    updated_ts DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS users (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    display_name TEXT,
                    xp BIGINT DEFAULT 0,
                    level INT DEFAULT 1,
                    balance BIGINT DEFAULT 0,
                    rating INT DEFAULT 1000,
                    words_text_total BIGINT DEFAULT 0,
                    words_audio_total BIGINT DEFAULT 0,
                    last_seen_ts DOUBLE PRECISION,
                    opt_out INT DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS word_stats (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    word TEXT NOT NULL,
                    count BIGINT DEFAULT 1,
                    PRIMARY KEY (guild_id, user_id, word)
                );
                CREATE TABLE IF NOT EXISTS prank_phrases (
                    phrase_id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    created_ts DOUBLE PRECISION NOT NULL,
                    mp3_path TEXT,
                    transcript TEXT,
                    transcript_ready BOOLEAN DEFAULT FALSE,
                    used_count INT DEFAULT 0,
                    deleted BOOLEAN DEFAULT FALSE,
                    is_favorite BOOLEAN DEFAULT FALSE,
                    name TEXT
                );
                CREATE TABLE IF NOT EXISTS user_profiles (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    profile_data JSONB DEFAULT '{}'::jsonb,
                    last_updated DOUBLE PRECISION,
                    PRIMARY KEY (guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS persistent_state (
                    guild_id BIGINT PRIMARY KEY,
                    last_log_channel_id BIGINT,
                    last_log_message_id BIGINT,
                    panel_channel_id BIGINT,
                    panel_message_id BIGINT
                );
            """)
            
            # Migrations
            await conn.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='prank_phrases' AND column_name='is_favorite') THEN 
                        ALTER TABLE prank_phrases ADD COLUMN is_favorite BOOLEAN DEFAULT FALSE; 
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='prank_phrases' AND column_name='name') THEN 
                        ALTER TABLE prank_phrases ADD COLUMN name TEXT; 
                    END IF;
                END $$;
            """)

            # Indexes
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_xp ON users(guild_id, xp DESC);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_rating ON users(guild_id, rating DESC);")

    # ---- Config ----
    async def get_config(self, guild_id: int) -> dict:
        row = await self.pool.fetchrow("SELECT settings FROM guild_configs WHERE guild_id=$1", guild_id)
        if row and row['settings']:
            return json.loads(row['settings'])
        return {}

    async def set_config_value(self, guild_id: int, key: str, value):
        cfg = await self.get_config(guild_id)
        cfg[key] = value
        await self.pool.execute("""
            INSERT INTO guild_configs (guild_id, settings) VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET settings = $2
        """, guild_id, json.dumps(cfg))

    # ---- Persistence (Panel & Logs) ----
    async def set_panel(self, guild_id: int, channel_id: int, message_id: int):
        await self.pool.execute("""
            INSERT INTO persistent_state (guild_id, panel_channel_id, panel_message_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE SET
                panel_channel_id=EXCLUDED.panel_channel_id,
                panel_message_id=EXCLUDED.panel_message_id
        """, guild_id, channel_id, message_id)

    async def get_panel(self, guild_id: int):
        row = await self.pool.fetchrow("SELECT panel_channel_id, panel_message_id FROM persistent_state WHERE guild_id=$1", guild_id)
        if row and row['panel_channel_id']:
            return (row['panel_channel_id'], row['panel_message_id'])
        return None

    async def set_last_log_msg(self, guild_id: int, channel_id: int, message_id: int):
        await self.pool.execute("""
            INSERT INTO persistent_state (guild_id, last_log_channel_id, last_log_message_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE SET
                last_log_channel_id=EXCLUDED.last_log_channel_id,
                last_log_message_id=EXCLUDED.last_log_message_id
        """, guild_id, channel_id, message_id)

    async def get_last_log_msg(self, guild_id: int):
        row = await self.pool.fetchrow("SELECT last_log_channel_id, last_log_message_id FROM persistent_state WHERE guild_id=$1", guild_id)
        if row and row['last_log_channel_id']:
            return (row['last_log_channel_id'], row['last_log_message_id'])
        return None

    # ---- Users & XP ----
    async def upsert_user(self, guild_id: int, user_id: int, display_name: str):
        await self.pool.execute("""
            INSERT INTO users (guild_id, user_id, display_name, last_seen_ts)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, users.display_name),
                last_seen_ts = EXCLUDED.last_seen_ts
        """, guild_id, user_id, display_name, time.time())

    async def get_user(self, guild_id: int, user_id: int):
        return await self.pool.fetchrow("SELECT * FROM users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id)

    async def get_user_id_by_name(self, guild_id: int, name: str) -> int | None:
        # Case-insensitive search
        name = name.strip()
        # 1. Try exact match (case-insensitive)
        row = await self.pool.fetchrow("SELECT user_id FROM users WHERE guild_id=$1 AND LOWER(display_name)=LOWER($2) LIMIT 1", guild_id, name)
        if row: return row['user_id']
        
        # 2. Try simple substring match if len > 2
        if len(name) > 2:
            row = await self.pool.fetchrow("SELECT user_id FROM users WHERE guild_id=$1 AND display_name ILIKE $2 LIMIT 1", guild_id, f"%{name}%")
            if row: return row['user_id']
            
        return None

    async def add_xp_and_words(self, guild_id: int, user_id: int, xp_amount: int, w_text: int, w_audio: int, words_list: list[str] = None):
        coin_reward = int(xp_amount * 0.1)
        await self.pool.execute("""
            INSERT INTO users (guild_id, user_id, xp, balance, words_text_total, words_audio_total)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET
                xp = users.xp + $3,
                balance = users.balance + $4,
                words_text_total = users.words_text_total + $5,
                words_audio_total = users.words_audio_total + $6
        """, guild_id, user_id, xp_amount, coin_reward, w_text, w_audio)

        await self.pool.execute("""
            UPDATE users SET level = FLOOR(SQRT(xp / 150)) + 1
            WHERE guild_id=$1 AND user_id=$2
        """, guild_id, user_id)

        if words_list:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    for w in words_list:
                        w = w.lower().strip()[:50]
                        if not w: continue
                        await conn.execute("""
                            INSERT INTO word_stats (guild_id, user_id, word, count)
                            VALUES ($1, $2, $3, 1)
                            ON CONFLICT (guild_id, user_id, word) DO UPDATE SET count = word_stats.count + 1
                        """, guild_id, user_id, w)

    async def set_user_opt_out(self, guild_id: int, user_id: int, is_opt_out: bool):
        val = 1 if is_opt_out else 0
        await self.pool.execute("""
            INSERT INTO users (guild_id, user_id, opt_out) VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET opt_out=$3
        """, guild_id, user_id, val)

    async def is_user_opt_out(self, guild_id: int, user_id: int) -> bool:
        val = await self.pool.fetchval("SELECT opt_out FROM users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id)
        return val == 1

    # ---- AI Profiles ----
    async def get_profile(self, guild_id: int, user_id: int) -> dict:
        row = await self.pool.fetchrow("SELECT profile_data FROM user_profiles WHERE guild_id=$1 AND user_id=$2", guild_id, user_id)
        if row and row['profile_data']:
            return json.loads(row['profile_data'])
        return {}

    async def upsert_profile(self, guild_id: int, user_id: int, data: dict):
        await self.pool.execute("""
            INSERT INTO user_profiles (guild_id, user_id, profile_data, last_updated)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET
                profile_data = EXCLUDED.profile_data,
                last_updated = EXCLUDED.last_updated
        """, guild_id, user_id, json.dumps(data), time.time())

    async def get_all_profiles(self, guild_id: int):
        # Join with users to get display_name
        return await self.pool.fetch("""
            SELECT p.user_id, u.display_name, p.last_updated
            FROM user_profiles p
            JOIN users u ON p.user_id = u.user_id AND p.guild_id = u.guild_id
            WHERE p.guild_id = $1
            ORDER BY p.last_updated DESC
        """, guild_id)

    async def append_achievements(self, guild_id: int, user_id: int, new_achs: list):
        """
        Appends new achievements to the existing list in profile_data['achievements'].
        """
        current = await self.get_profile(guild_id, user_id)
        existing = current.get('achievements', [])
        if not isinstance(existing, list): existing = []
        
        # Avoid duplicates by title
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
        """Clears achievements for ALL users in the guild."""
        await self.pool.execute("""
            UPDATE user_profiles 
            SET profile_data = jsonb_set(profile_data, '{achievements}', '[]'::jsonb)
            WHERE guild_id = $1
        """, guild_id)

    # ---- Economy & Games ----
    async def get_balance(self, guild_id: int, user_id: int) -> int:
        return await self.pool.fetchval("SELECT balance FROM users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id) or 0

    async def update_balance(self, guild_id: int, user_id: int, delta: int):
        await self.pool.execute("""
            UPDATE users SET balance = GREATEST(0, balance + $3) WHERE guild_id=$1 AND user_id=$2
        """, guild_id, user_id, delta)

    async def get_rating(self, guild_id: int, user_id: int) -> int:
        return await self.pool.fetchval("SELECT rating FROM users WHERE guild_id=$1 AND user_id=$2", guild_id, user_id) or 1000

    async def update_rating(self, guild_id: int, user_id: int, delta: int):
        await self.pool.execute("""
            UPDATE users SET rating = rating + $3 WHERE guild_id=$1 AND user_id=$2
        """, guild_id, user_id, delta)

    async def get_top_users(self, guild_id: int, limit=10):
        return await self.pool.fetch("""
            SELECT user_id, xp, level, rating FROM users 
            WHERE guild_id=$1 
            ORDER BY xp DESC LIMIT $2
        """, guild_id, limit)

    async def get_word_stats(self, guild_id: int, user_id: int, limit=10):
        return await self.pool.fetch("""
            SELECT word, count FROM word_stats
            WHERE guild_id=$1 AND user_id=$2
            ORDER BY count DESC LIMIT $3
        """, guild_id, user_id, limit)

    # ---- Prank Phrases ----
    async def create_phrase_row(self, guild_id: int, user_id: int, created_ts: float, mp3_path: str) -> int:
        return await self.pool.fetchval("""
            INSERT INTO prank_phrases (guild_id, user_id, created_ts, mp3_path)
            VALUES ($1, $2, $3, $4) RETURNING phrase_id
        """, guild_id, user_id, float(created_ts), mp3_path)

    async def update_phrase_path(self, phrase_id: int, mp3_path: str):
        await self.pool.execute("UPDATE prank_phrases SET mp3_path=$1 WHERE phrase_id=$2", mp3_path, phrase_id)

    async def mark_phrase_transcript(self, phrase_id: int, transcript: str):
        await self.pool.execute("""
            UPDATE prank_phrases SET transcript=$1, transcript_ready=TRUE 
            WHERE phrase_id=$2
        """, transcript, phrase_id)
        
    async def mark_phrase_ready(self, phrase_id: int):
        await self.pool.execute("UPDATE prank_phrases SET transcript_ready=TRUE WHERE phrase_id=$1", phrase_id)

    async def take_pending_phrase(self, guild_id: int):
        return await self.pool.fetchrow("""
            SELECT phrase_id, user_id, mp3_path FROM prank_phrases
            WHERE guild_id=$1 AND transcript_ready=FALSE AND deleted=FALSE
            ORDER BY created_ts ASC LIMIT 1
        """, guild_id)

    async def random_ready_phrase(self, guild_id: int):
        row = await self.pool.fetchrow("""
            SELECT phrase_id, mp3_path FROM prank_phrases
            WHERE guild_id=$1 AND transcript_ready=TRUE AND deleted=FALSE
            ORDER BY RANDOM() LIMIT 1
        """, guild_id)
        if row:
            return (row['phrase_id'], row['mp3_path'])
        return None
    
    async def get_phrase(self, phrase_id: int):
        return await self.pool.fetchrow("SELECT * FROM prank_phrases WHERE phrase_id=$1", phrase_id)

    async def list_recent_phrases(self, guild_id: int, limit=10):
        # Only normal (non-favorite) or all? Let's show all
        return await self.pool.fetch("""
            SELECT phrase_id, user_id, transcript, used_count, is_favorite, name
            FROM prank_phrases WHERE guild_id=$1 AND deleted=FALSE
            ORDER BY created_ts DESC LIMIT $2
        """, guild_id, limit)

    async def count_phrases(self, guild_id: int):
        return await self.pool.fetchrow("""
            SELECT COUNT(DISTINCT user_id) as users, COUNT(*) as total 
            FROM prank_phrases WHERE guild_id=$1 AND deleted=FALSE
        """, guild_id)

    async def record_play(self, phrase_id: int):
        await self.pool.execute("UPDATE prank_phrases SET used_count=used_count+1 WHERE phrase_id=$1", phrase_id)

    async def delete_phrase(self, phrase_id: int):
        await self.pool.execute("UPDATE prank_phrases SET deleted=TRUE WHERE phrase_id=$1", phrase_id)

    # --- New Methods for Rotation & Favorites ---

    async def set_phrase_favorite(self, phrase_id: int, is_fav: bool):
        await self.pool.execute("UPDATE prank_phrases SET is_favorite=$1 WHERE phrase_id=$2", is_fav, phrase_id)

    async def set_phrase_name(self, phrase_id: int, name: str):
        await self.pool.execute("UPDATE prank_phrases SET name=$1 WHERE phrase_id=$2", name, phrase_id)

    async def get_user_phrase_stats(self, guild_id: int, user_id: int):
        # Returns {count, newest_ts}
        return await self.pool.fetchrow("""
            SELECT COUNT(*) as cnt, MAX(created_ts) as newest
            FROM prank_phrases
            WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
        """, guild_id, user_id)

    async def enforce_phrase_limit(self, guild_id: int, user_id: int, max_per_user: int) -> list[str]:
        if max_per_user <= 0:
            return []
        
        # We enforce limit ONLY on non-favorites.
        # But should favorites count towards limit?
        # Logic: If I have 30 slots, and 5 favorites. I can have 25 normal phrases.
        # Total count = 30.
        
        # 1. Get all phrases (fav + normal) sorted newest first
        # But we only want to delete NORMAL phrases that are pushed out of the "top N".
        
        # It's complicated. Simple logic:
        # Keep N phrases total. Favorites are never deleted automatically.
        # If I have 30 favorites and limit 30, I can't record new phrases.
        
        # Query: Find NORMAL phrases that are older than the N-th phrase of ANY type.
        # Actually easier: Just delete OLD NORMAL phrases if Total Count > Limit.
        
        # Fetch ID of the N-th newest phrase (cutoff).
        # Anything older than that AND not favorite -> delete.
        
        cutoff_row = await self.pool.fetchrow("""
            SELECT created_ts FROM prank_phrases
            WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
            ORDER BY created_ts DESC
            OFFSET $3 LIMIT 1
        """, guild_id, user_id, max_per_user - 1) # Offset 29 gets 30th item
        
        if not cutoff_row:
            return [] # We don't have enough phrases to trigger limit
            
        cutoff_ts = cutoff_row['created_ts']
        
        # Delete non-favorite phrases strictly older than cutoff (or equal if we want strictly N)
        rows = await self.pool.fetch("""
            SELECT phrase_id, mp3_path FROM prank_phrases
            WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
            AND is_favorite=FALSE
            AND created_ts <= $3
            AND phrase_id NOT IN (
                SELECT phrase_id FROM prank_phrases 
                WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
                ORDER BY created_ts DESC LIMIT $4
            )
        """, guild_id, user_id, cutoff_ts, max_per_user)
        # The logic: delete things older than cutoff, BUT ensure we keep top N (in case favorites are old).
        # Actually, simpler:
        # Delete IDs that are NOT in the top N newest list AND are NOT favorites.
        
        # Let's retry query:
        # Delete from phrases where ID NOT IN (Select Top N) AND is_favorite=False.
        
        rows = await self.pool.fetch("""
            SELECT phrase_id, mp3_path FROM prank_phrases
            WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
            AND is_favorite=FALSE
            AND phrase_id NOT IN (
                SELECT phrase_id FROM prank_phrases
                WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
                ORDER BY created_ts DESC
                LIMIT $3
            )
        """, guild_id, user_id, max_per_user)

        paths = []
        if rows:
            ids = [r['phrase_id'] for r in rows]
            paths = [r['mp3_path'] for r in rows if r['mp3_path']]
            await self.pool.execute("UPDATE prank_phrases SET deleted=TRUE WHERE phrase_id = ANY($1::int[])", ids)
            
        return paths
        
    async def get_user_favorites(self, guild_id: int):
        return await self.pool.fetch("""
            SELECT phrase_id, user_id, name, created_ts, mp3_path 
            FROM prank_phrases 
            WHERE guild_id=$1 AND deleted=FALSE AND is_favorite=TRUE
            ORDER BY created_ts DESC
        """, guild_id)
        
    async def get_all_user_phrases(self, guild_id: int, user_id: int, limit=50):
        return await self.pool.fetch("""
            SELECT phrase_id, name, created_ts, is_favorite 
            FROM prank_phrases 
            WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
            ORDER BY created_ts DESC LIMIT $3
        """, guild_id, user_id, limit)