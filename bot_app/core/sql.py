# Schema Initialization
INIT_SCHEMA_GUILD_CONFIGS = """
CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id BIGINT PRIMARY KEY,
    settings JSONB DEFAULT '{}'::jsonb
);
"""

INIT_SCHEMA_GUILD_PANELS = """
CREATE TABLE IF NOT EXISTS guild_panels (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    updated_ts DOUBLE PRECISION
);
"""

INIT_SCHEMA_USERS = """
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
    daily_last_claim_ts DOUBLE PRECISION DEFAULT 0,
    free_phrase_plays INT DEFAULT 0,
    total_speech_seconds DOUBLE PRECISION DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""

INIT_SCHEMA_SOUNDPAD = """
CREATE TABLE IF NOT EXISTS soundpad_sounds (
    sound_id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_ts DOUBLE PRECISION,
    duration_sec DOUBLE PRECISION,
    is_verified BOOLEAN DEFAULT TRUE
);
"""

INIT_SCHEMA_REMINDERS = """
CREATE TABLE IF NOT EXISTS reminders (
    remind_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    created_ts DOUBLE PRECISION,
    due_ts DOUBLE PRECISION,
    text TEXT,
    completed BOOLEAN DEFAULT FALSE
);
"""

INIT_SCHEMA_AFK = """
CREATE TABLE IF NOT EXISTS afk_status (
    user_id BIGINT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    message TEXT,
    since_ts DOUBLE PRECISION
);
"""

INIT_SCHEMA_WORD_STATS = """
CREATE TABLE IF NOT EXISTS word_stats (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    word TEXT NOT NULL,
    count BIGINT DEFAULT 1,
    PRIMARY KEY (guild_id, user_id, word)
);
"""

INIT_SCHEMA_PRANK_PHRASES = """
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
"""

INIT_SCHEMA_USER_PROFILES = """
CREATE TABLE IF NOT EXISTS user_profiles (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    profile_data JSONB DEFAULT '{}'::jsonb,
    last_updated DOUBLE PRECISION,
    PRIMARY KEY (guild_id, user_id)
);
"""

INIT_SCHEMA_PERSISTENT_STATE = """
CREATE TABLE IF NOT EXISTS persistent_state (
    guild_id BIGINT PRIMARY KEY,
    last_log_channel_id BIGINT,
    last_log_message_id BIGINT,
    panel_channel_id BIGINT,
    panel_message_id BIGINT
);
"""

INIT_SCHEMA_INVENTORY = """
CREATE TABLE IF NOT EXISTS user_inventory (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    item_id TEXT NOT NULL,
    count INT DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, item_id)
);
"""

INIT_SCHEMA_BUFFS = """
CREATE TABLE IF NOT EXISTS active_buffs (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    buff_id TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    value DOUBLE PRECISION DEFAULT 1.0,
    PRIMARY KEY (guild_id, user_id, buff_id)
);
"""

MIGRATION_V4 = """
DO $$ 
BEGIN 
    -- Users migrations
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='daily_last_claim_ts') THEN 
        ALTER TABLE users ADD COLUMN daily_last_claim_ts DOUBLE PRECISION DEFAULT 0; 
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='free_phrase_plays') THEN 
        ALTER TABLE users ADD COLUMN free_phrase_plays INT DEFAULT 0; 
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='total_speech_seconds') THEN 
        ALTER TABLE users ADD COLUMN total_speech_seconds DOUBLE PRECISION DEFAULT 0; 
    END IF;

    -- Prank phrases migrations (legacy check)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='prank_phrases' AND column_name='is_favorite') THEN 
        ALTER TABLE prank_phrases ADD COLUMN is_favorite BOOLEAN DEFAULT FALSE; 
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='prank_phrases' AND column_name='name') THEN 
        ALTER TABLE prank_phrases ADD COLUMN name TEXT; 
    END IF;
END $$;
"""

INIT_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_users_xp ON users(guild_id, xp DESC);
CREATE INDEX IF NOT EXISTS idx_users_rating ON users(guild_id, rating DESC);
CREATE INDEX IF NOT EXISTS idx_soundpad_guild ON soundpad_sounds(guild_id);
"""

# Queries
GET_CONFIG = "SELECT settings FROM guild_configs WHERE guild_id=$1"

SET_CONFIG = """
INSERT INTO guild_configs (guild_id, settings) VALUES ($1, $2)
ON CONFLICT (guild_id) DO UPDATE SET settings = $2
"""

SET_PANEL = """
INSERT INTO persistent_state (guild_id, panel_channel_id, panel_message_id)
VALUES ($1, $2, $3)
ON CONFLICT (guild_id) DO UPDATE SET
    panel_channel_id=EXCLUDED.panel_channel_id,
    panel_message_id=EXCLUDED.panel_message_id
"""

GET_PANEL = "SELECT panel_channel_id, panel_message_id FROM persistent_state WHERE guild_id=$1"

SET_LAST_LOG = """
INSERT INTO persistent_state (guild_id, last_log_channel_id, last_log_message_id)
VALUES ($1, $2, $3)
ON CONFLICT (guild_id) DO UPDATE SET
    last_log_channel_id=EXCLUDED.last_log_channel_id,
    last_log_message_id=EXCLUDED.last_log_message_id
"""

GET_LAST_LOG = "SELECT last_log_channel_id, last_log_message_id FROM persistent_state WHERE guild_id=$1"

UPSERT_USER = """
INSERT INTO users (guild_id, user_id, display_name, last_seen_ts)
VALUES ($1, $2, $3, $4)
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    display_name = COALESCE(EXCLUDED.display_name, users.display_name),
    last_seen_ts = EXCLUDED.last_seen_ts
"""

GET_USER = "SELECT * FROM users WHERE guild_id=$1 AND user_id=$2"

GET_USER_ID_BY_NAME_EXACT = "SELECT user_id FROM users WHERE guild_id=$1 AND LOWER(display_name)=LOWER($2) LIMIT 1"
GET_USER_ID_BY_NAME_LIKE = "SELECT user_id FROM users WHERE guild_id=$1 AND display_name ILIKE $2 LIMIT 1"

ADD_XP_AND_WORDS = """
INSERT INTO users (guild_id, user_id, xp, balance, words_text_total, words_audio_total)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    xp = users.xp + $3,
    balance = users.balance + $4,
    words_text_total = users.words_text_total + $5,
    words_audio_total = users.words_audio_total + $6
"""

UPDATE_USER_LEVEL = """
UPDATE users SET level = FLOOR(SQRT(xp / 150)) + 1
WHERE guild_id=$1 AND user_id=$2
"""

UPSERT_WORD_STAT = """
INSERT INTO word_stats (guild_id, user_id, word, count)
VALUES ($1, $2, $3, 1)
ON CONFLICT (guild_id, user_id, word) DO UPDATE SET count = word_stats.count + 1
"""

SET_USER_OPT_OUT = """
INSERT INTO users (guild_id, user_id, opt_out) VALUES ($1, $2, $3)
ON CONFLICT (guild_id, user_id) DO UPDATE SET opt_out=$3
"""

GET_USER_OPT_OUT = "SELECT opt_out FROM users WHERE guild_id=$1 AND user_id=$2"

UPSERT_PROFILE = """
INSERT INTO user_profiles (guild_id, user_id, profile_data, last_updated)
VALUES ($1, $2, $3, $4)
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    profile_data = EXCLUDED.profile_data,
    last_updated = EXCLUDED.last_updated
"""

GET_PROFILE = "SELECT profile_data FROM user_profiles WHERE guild_id=$1 AND user_id=$2"

GET_ALL_PROFILES = """
SELECT p.user_id, u.display_name, p.last_updated, p.profile_data
FROM user_profiles p
JOIN users u ON p.user_id = u.user_id AND p.guild_id = u.guild_id
WHERE p.guild_id = $1
ORDER BY p.last_updated DESC
"""

RESET_ACHIEVEMENTS = """
UPDATE user_profiles 
SET profile_data = jsonb_set(profile_data, '{achievements}', '[]'::jsonb)
WHERE guild_id = $1
"""

INSERT_PHRASE = """
INSERT INTO prank_phrases (guild_id, user_id, created_ts, mp3_path)
VALUES ($1, $2, $3, $4) RETURNING phrase_id
"""

TAKE_PENDING_PHRASE = """
SELECT phrase_id, user_id, mp3_path FROM prank_phrases
WHERE guild_id=$1 AND transcript_ready=FALSE AND deleted=FALSE
ORDER BY created_ts ASC LIMIT 1
"""

RANDOM_READY_PHRASE = """
SELECT phrase_id, mp3_path FROM prank_phrases
WHERE guild_id=$1 AND transcript_ready=TRUE AND deleted=FALSE
ORDER BY RANDOM() LIMIT 1
"""

LIST_RECENT_PHRASES = """
SELECT phrase_id, user_id, transcript, used_count, is_favorite, name
FROM prank_phrases WHERE guild_id=$1 AND deleted=FALSE
ORDER BY created_ts DESC LIMIT $2
"""

COUNT_PHRASES = """
SELECT COUNT(DISTINCT user_id) as users, COUNT(*) as total 
FROM prank_phrases WHERE guild_id=$1 AND deleted=FALSE
"""

DELETE_OLD_PHRASES = """
SELECT phrase_id, mp3_path FROM prank_phrases
WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
AND is_favorite=FALSE
AND phrase_id NOT IN (
    SELECT phrase_id FROM prank_phrases
    WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
    ORDER BY created_ts DESC
    LIMIT $3
)
"""

UPDATE_PHRASE_DELETED = "UPDATE prank_phrases SET deleted=TRUE WHERE phrase_id = ANY($1::int[])"

GET_USER_FAVORITES = """
SELECT phrase_id, user_id, name, created_ts, mp3_path 
FROM prank_phrases 
WHERE guild_id=$1 AND deleted=FALSE AND is_favorite=TRUE
ORDER BY created_ts DESC
"""

GET_ALL_USER_PHRASES = """
SELECT phrase_id, name, created_ts, is_favorite 
FROM prank_phrases 
WHERE guild_id=$1 AND user_id=$2 AND deleted=FALSE
ORDER BY created_ts DESC LIMIT $3
"""

# --- NEW SQL QUERIES FOR V4.0 ---

# Soundpad
INSERT_SOUNDPAD = """
INSERT INTO soundpad_sounds (guild_id, user_id, name, file_path, created_ts, duration_sec)
VALUES ($1, $2, $3, $4, $5, $6) RETURNING sound_id
"""

GET_SOUNDPAD_SOUNDS = """
SELECT sound_id, user_id, name, file_path 
FROM soundpad_sounds 
WHERE guild_id=$1 AND is_verified=TRUE
ORDER BY name ASC
"""

GET_SOUNDPAD_SOUND_BY_NAME = """
SELECT * FROM soundpad_sounds 
WHERE guild_id=$1 AND LOWER(name)=LOWER($2) AND is_verified=TRUE
LIMIT 1
"""

# Reminders
INSERT_REMINDER = """
INSERT INTO reminders (user_id, channel_id, created_ts, due_ts, text)
VALUES ($1, $2, $3, $4, $5) RETURNING remind_id
"""

GET_PENDING_REMINDERS = """
SELECT remind_id, user_id, channel_id, text, due_ts
FROM reminders
WHERE due_ts <= $1 AND completed=FALSE
"""

MARK_REMINDER_COMPLETED = "UPDATE reminders SET completed=TRUE WHERE remind_id=$1"

# AFK
SET_AFK = """
INSERT INTO afk_status (user_id, guild_id, message, since_ts)
VALUES ($1, $2, $3, $4)
ON CONFLICT (user_id) DO UPDATE SET
    message = EXCLUDED.message,
    since_ts = EXCLUDED.since_ts,
    guild_id = EXCLUDED.guild_id
"""

GET_AFK = "SELECT message, since_ts FROM afk_status WHERE user_id=$1"
DELETE_AFK = "DELETE FROM afk_status WHERE user_id=$1"

# --- SAFETY & CLEANUP ---
DELETE_ALL_NON_FAV_PHRASES = """
DELETE FROM prank_phrases 
WHERE guild_id=$1 AND is_favorite IS NOT TRUE
"""

# Daily & Economy
UPDATE_DAILY_CLAIM = """
UPDATE users SET daily_last_claim_ts=$3, balance=balance+$4 
WHERE guild_id=$1 AND user_id=$2
"""

ADD_FREE_PLAYS = "UPDATE users SET free_phrase_plays = free_phrase_plays + $3 WHERE guild_id=$1 AND user_id=$2"
DECREMENT_FREE_PLAYS = "UPDATE users SET free_phrase_plays = GREATEST(0, free_phrase_plays - 1) WHERE guild_id=$1 AND user_id=$2"

# Progression Reset (Soft)
RESET_XP_KEEP_LEVEL = "UPDATE users SET xp=0 WHERE guild_id=$1"

# --- INVENTORY & BUFFS QUERIES ---
ADD_ITEM = """
INSERT INTO user_inventory (guild_id, user_id, item_id, count)
VALUES ($1, $2, $3, $4)
ON CONFLICT (guild_id, user_id, item_id) DO UPDATE SET count = user_inventory.count + $4
"""

REMOVE_ITEM = """
UPDATE user_inventory SET count = count - $4 
WHERE guild_id=$1 AND user_id=$2 AND item_id=$3 AND count >= $4
RETURNING count
"""

GET_INVENTORY = "SELECT item_id, count FROM user_inventory WHERE guild_id=$1 AND user_id=$2 AND count > 0"

UPSERT_BUFF = """
INSERT INTO active_buffs (guild_id, user_id, buff_id, expires_at, value)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (guild_id, user_id, buff_id) DO UPDATE SET 
    expires_at = GREATEST(active_buffs.expires_at, $4),
    value = $5
"""

GET_ACTIVE_BUFFS = "SELECT buff_id, expires_at, value FROM active_buffs WHERE guild_id=$1 AND user_id=$2 AND expires_at > $3"
GET_SPECIFIC_BUFF = "SELECT expires_at, value FROM active_buffs WHERE guild_id=$1 AND user_id=$2 AND buff_id=$3 AND expires_at > $4"
CLEANUP_BUFFS = "DELETE FROM active_buffs WHERE expires_at < $1"

UPDATE_SPEECH_STATS = """
UPDATE users SET total_speech_seconds = total_speech_seconds + $3 
WHERE guild_id=$1 AND user_id=$2
"""
