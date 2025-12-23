import os
import sys
import logging
import warnings
import asyncio
import time
import datetime

import discord
import discord.opus
from discord.ext import commands

from pydub import AudioSegment

from .core.config import (
    TOKEN,
    PROJECT_DIR,
    FFMPEG_DIR,
    OPUS_DLL_NAME,
    DEFAULT_PRESENCE_POLL_SECONDS,
    FFMPEG_EXE,
)
from .core.app_db import AppDB
from .core.runtime_settings import RuntimeSettings
from .ui.control_panel import ControlPanelView, build_home_embed
from .features.voice_logger import VoiceLogger
from .features.help_system import CustomHelpCommand

# --- Setup Paths & Env ---
if "PATH" in os.environ and FFMPEG_DIR and (FFMPEG_DIR not in os.environ["PATH"]):
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ["PATH"]

warnings.filterwarnings("ignore", message="Couldn't find ffmpeg or avconv*", category=RuntimeWarning)

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot_debug.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
# Silence noisy loggers
for lib in ["discord.ext.voice_recv.reader", "discord.ext.voice_recv.rtp", "discord.ext.voice_recv.opus"]:
    logging.getLogger(lib).setLevel(logging.ERROR)

# --- Bot Init ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=CustomHelpCommand())

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:80013002@localhost:5432/logerbot_db")
db = AppDB(DSN)

# Global State
settings_cache: dict[int, RuntimeSettings] = {}
loggers: dict[int, VoiceLogger] = {}
user_spam_cooldowns: dict[int, float] = {}
tasks: list[asyncio.Task] = []

# --- Helpers ---

def _load_opus():
    if sys.platform != "win32":
        if not discord.opus.is_loaded():
            try: discord.opus.load_opus("libopus.so.0")
            except: pass
        return
    opus_path = os.path.join(PROJECT_DIR, OPUS_DLL_NAME)
    if not discord.opus.is_loaded():
        if os.path.exists(opus_path): discord.opus.load_opus(opus_path)
        else:
            print(f"❌ Opus DLL not found: {opus_path}")
            sys.exit(1)

def _patch_decoder():
    _original = discord.opus.Decoder.decode
    def patched(self, *args, **kwargs):
        try: return _original(self, *args, **kwargs)
        except: return b""
    discord.opus.Decoder.decode = patched

def _setup_pydub():
    if sys.platform != "win32":
        AudioSegment.converter = "ffmpeg"
        AudioSegment.ffprobe = "ffprobe"
        return
    ffprobe = os.path.join(FFMPEG_DIR, "ffprobe.exe")
    if os.path.exists(FFMPEG_EXE): AudioSegment.converter = FFMPEG_EXE
    if os.path.exists(ffprobe): AudioSegment.ffprobe = ffprobe

def get_settings(guild_id: int) -> RuntimeSettings:
    s = settings_cache.get(guild_id)
    if not s:
        s = RuntimeSettings(db, guild_id)
        asyncio.create_task(s.load())
        settings_cache[guild_id] = s
    return s

# --- Core Logic ---

async def ensure_logger_started(interaction: discord.Interaction):
    g = interaction.guild
    if not g: return
    
    member = interaction.user
    if not isinstance(member, discord.Member) or not member.voice:
        return await interaction.followup.send("Сначала зайдите в голосовой канал.", ephemeral=True)
    
    logger = loggers.get(g.id)
    if logger and logger.is_recording: return

    settings = get_settings(g.id)
    logger = VoiceLogger(bot, guild_id=g.id, text_channel_id=interaction.channel.id, db=db, settings=settings)
    loggers[g.id] = logger
    
    # Link Dashboard (Persistence)
    panel_info = await db.get_panel(g.id)
    if panel_info:
        c_id, m_id = panel_info
        try:
            ch = g.get_channel(c_id)
            if ch:
                msg = await ch.fetch_message(m_id)
                logger.dashboard_message = msg
                logger.view = ControlPanelView(AppWrapper(), g.id)
        except: pass

    await logger.start(guild=g, voice_channel=member.voice.channel, text_channel=interaction.channel)

async def ensure_logger_stopped(guild_id: int):
    l = loggers.get(guild_id)
    if l:
        await l.stop()
        loggers.pop(guild_id, None)

class AppWrapper:
    def __init__(self):
        self.db = db
        self.loggers = loggers
    def get_settings(self, gid): return get_settings(gid)
    async def ensure_logger_started(self, i): await ensure_logger_started(i)
    async def ensure_logger_stopped(self, gid): await ensure_logger_stopped(gid)

# --- Panel Management Logic ---

async def pick_control_channel(guild: discord.Guild) -> discord.TextChannel | None:
    existing = discord.utils.get(guild.text_channels, name="loger-control")
    if existing and existing.permissions_for(guild.me).send_messages:
        return existing
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        return guild.system_channel
    for ch in guild.text_channels:
        perms = ch.permissions_for(guild.me)
        if perms.send_messages and perms.read_message_history and perms.embed_links:
            return ch
    return None

async def create_panel_in_channel(guild: discord.Guild, channel: discord.TextChannel) -> discord.Message | None:
    perms = channel.permissions_for(guild.me)
    if not (perms.send_messages and perms.embed_links and perms.read_message_history):
        return None

    view = ControlPanelView(AppWrapper(), guild.id)
    settings = get_settings(guild.id)
    await settings.load()
    logger = loggers.get(guild.id)
    stats = await db.count_phrases(guild.id)
    embed = build_home_embed(guild, logger, settings, db, stats)

    # Clean legacy if sending new
    if channel.name == "loger-control":
        try: await channel.purge(limit=10, check=lambda m: m.author == bot.user)
        except: pass

    msg = await channel.send(embed=embed, view=view)
    await db.set_panel(guild.id, channel.id, msg.id)
    bot.add_view(view)
    return msg

async def ensure_panel_logic(guild: discord.Guild, force_create_channel=False):
    channel = None
    if force_create_channel:
        existing = discord.utils.get(guild.text_channels, name="loger-control")
        if not existing:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                channel = await guild.create_text_channel("loger-control", overwrites=overwrites)
            except: pass
        else:
            channel = existing

    if not channel:
        channel = await pick_control_channel(guild)
    if not channel: return

    panel_info = await db.get_panel(guild.id)
    panel_msg_id = panel_info[1] if panel_info else None

    # 1. Clean Channel (Delete all bot messages except the current panel ID)
    try:
        def is_me_trash(m):
            return m.author == bot.user and m.id != panel_msg_id
        await channel.purge(limit=50, check=is_me_trash)
    except Exception as e:
        print(f"Cleanup error in {guild.name}: {e}")

    # 2. Check / Restore Panel
    view = ControlPanelView(AppWrapper(), guild.id)
    
    if panel_info:
        ch_id, msg_id = panel_info
        # Only if channel matches (otherwise stored DB is wrong channel)
        if ch_id == channel.id:
            try:
                msg = await channel.fetch_message(msg_id)
                
                # Check Age: if older than 2 days, recreate to keep it fresh at bottom
                age = datetime.datetime.now(datetime.timezone.utc) - msg.created_at
                if age.days > 2:
                    await msg.delete()
                    raise Exception("Panel too old, recreating")

                # Try to edit
                settings = get_settings(guild.id)
                await settings.load()
                logger = loggers.get(guild.id)
                stats = await db.count_phrases(guild.id)
                embed = build_home_embed(guild, logger, settings, db, stats)
                
                await msg.edit(embed=embed, view=view)
                bot.add_view(view)
                return
            except Exception as e:
                # If fetch failed, or edit failed, or outdated -> We fall through to create new
                print(f"Panel restore failed ({e}), creating new.")
    
    # 3. Create New
    await create_panel_in_channel(guild, channel)

# Inject dependencies
bot.db = db
bot.loggers = loggers
bot.get_settings = lambda gid: get_settings(gid)
bot.ensure_panel_func = ensure_panel_logic

# --- Events ---

@bot.event
async def on_ready():
    print(f"✅ LogerBot v3.0 Started as {bot.user}")
    
    try:
        await db.connect()
        print("✅ Database Connected")
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return

    try:
        await bot.load_extension("bot_app.cogs.general_commands")
        await bot.load_extension("bot_app.cogs.economy_commands")
        await bot.load_extension("bot_app.cogs.admin_commands")
        print("✅ Cogs Loaded")
    except Exception as e:
        print(f"❌ Cogs Error: {e}")

    _load_opus()
    _patch_decoder()
    _setup_pydub()

    print("🔄 Restoring state...")
    loggers.clear()
    
    for g in bot.guilds:
        # 1. Cleanup pending last log message record (we don't need it if we purged channel)
        # But maybe logs were in another channel? Let's clean just in case
        last_log = await db.get_last_log_msg(g.id)
        if last_log:
            lc_id, lm_id = last_log
            try:
                ch = g.get_channel(lc_id)
                if ch:
                    msg = await ch.fetch_message(lm_id)
                    await msg.delete()
            except: pass

        # 2. Clean & Restore Panel
        await ensure_panel_logic(g, force_create_channel=False)

    tasks.append(asyncio.create_task(presence_poll_loop()))
    tasks.append(asyncio.create_task(auto_cleanup_loop()))

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    
    if message.content.startswith("!"):
        try: await message.delete()
        except: pass
    
    await bot.process_commands(message)
    
    if message.guild:
        uid = message.author.id
        now = time.time()
        if now - user_spam_cooldowns.get(uid, 0) > 2.0:
            user_spam_cooldowns[uid] = now
            words = message.content.split()
            if words:
                await db.upsert_user(message.guild.id, uid, message.author.display_name)
                await db.add_xp_and_words(message.guild.id, uid, min(len(words), 20), w_text=len(words), w_audio=0, words_list=words)
        
        l = loggers.get(message.guild.id)
        if l and l.is_recording:
            l.log_chat_message(message.author.name, message.content)

@bot.event
async def on_voice_state_update(member, before, after):
    if not member.guild: return
    l = loggers.get(member.guild.id)
    if not l or not l.is_recording: return
    
    mon_id = l.voice_channel_id
    if after.channel and after.channel.id == mon_id and (not before.channel or before.channel.id != mon_id):
        l.log_event(time.time(), "🚪", f"{member.name} зашел.")
    elif before.channel and before.channel.id == mon_id and (not after.channel or after.channel.id != mon_id):
        l.log_event(time.time(), "🚪", f"{member.name} вышел.")

@bot.event
async def on_presence_update(before, after):
    if not after.guild: return
    logger = loggers.get(after.guild.id)
    if not logger or not logger.is_recording: return
    
    if not after.voice or not after.voice.channel or after.voice.channel.id != logger.voice_channel_id:
        return

    old_acts = {a.name for a in before.activities}
    new_acts = {a.name for a in after.activities}
    started = new_acts - old_acts
    
    ts = time.time()
    for act in started:
        logger.log_event(ts, "🎮", f"{after.name} начал играть в: {act}")

@bot.event
async def on_guild_join(guild):
    await ensure_panel_logic(guild, force_create_channel=True)

# --- Loops ---

async def presence_poll_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(DEFAULT_PRESENCE_POLL_SECONDS)

async def auto_cleanup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(600)

# --- Entry Point ---

async def main():
    async with bot:
        try:
            await bot.start(TOKEN)
        finally:
            print("🛑 Shutdown...")
            await asyncio.gather(*[l.stop() for l in loggers.values()])
            await db.close()

def run():
    if not TOKEN: raise RuntimeError("No Token")
    try: asyncio.run(main())
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    run()