import os
import sys
import logging
import warnings
import asyncio
import discord
from discord.ext import commands

from .core.config import TOKEN, PROJECT_DIR
from .core.app_db import AppDB
from .features.help_system import CustomHelpCommand
from .core import audio_setup
from .core import state
from .features import panel_control

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

warnings.filterwarnings("ignore", message="Couldn't find ffmpeg or avconv*", category=RuntimeWarning)

# --- Bot Init ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=CustomHelpCommand())

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:80013002@localhost:5432/logerbot_db")
app_db = AppDB(DSN)

# Inject Global State
state.db = app_db
bot.db = app_db
bot.loggers = state.loggers
# Helper lambda to match old interface if cogs use it
bot.get_settings = state.get_settings
# Inject panel logic for reuse if needed (though it's better to import)
bot.ensure_panel_func = lambda g, force=False: panel_control.ensure_panel_logic(bot, g, app_db, force)

# --- Events ---

@bot.event
async def on_ready():
    print(f"✅ LogerBot v3.0 Started as {bot.user}")
    
    try:
        await app_db.connect()
        print("✅ Database Connected")
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return

    # Load Cogs
    initial_extensions = [
        "bot_app.cogs.general_commands",
        "bot_app.cogs.economy_commands",
        "bot_app.cogs.admin_commands",
        "bot_app.cogs.events",
        # New v4.0 Cogs
        "bot_app.cogs.debug",
        "bot_app.cogs.utilities",
        "bot_app.cogs.soundpad",
        "bot_app.cogs.user_interaction",
        "bot_app.cogs.progression",
        "bot_app.cogs.fun",
        "bot_app.cogs.ai_fun",
    ]

    for ext in initial_extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Loaded {ext}")
        except Exception as e:
            print(f"❌ Failed to load {ext}: {e}")

    # Setup Audio
    audio_setup.setup_audio_libraries()
    
    # Start Log Archiver
    from bot_app.features.log_archiver import LogArchiver
    bot.archiver = LogArchiver(bot)
    asyncio.create_task(bot.archiver.start())

    print("🔄 Restoring state...")
    state.loggers.clear()
    
    for g in bot.guilds:
        # 1. Cleanup pending last log message record
        last_log = await app_db.get_last_log_msg(g.id)
        if last_log:
            lc_id, lm_id = last_log
            try:
                ch = g.get_channel(lc_id)
                if ch:
                    msg = await ch.fetch_message(lm_id)
                    await msg.delete()
            except Exception: 
                pass

        # 2. Clean & Restore Panel
        # We start background task for panel logic to not block on_ready too long
        asyncio.create_task(panel_control.ensure_panel_logic(bot, g, app_db, force_create_channel=False))

# --- Entry Point ---

async def main():
    async with bot:
        try:
            await bot.start(TOKEN)
        finally:
            print("🛑 Shutdown...")
            # Stop all loggers
            await asyncio.gather(*[l.stop() for l in state.loggers.values()])
            await app_db.close()

def run():
    if not TOKEN: 
        raise RuntimeError("No Token")
    try: 
        asyncio.run(main())
    except KeyboardInterrupt: 
        pass

if __name__ == "__main__":
    run()
