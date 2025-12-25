import os
import sys
import logging
import warnings
import asyncio
import discord
import aiohttp
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
bot.ensure_panel_func = lambda g, force_create_channel=False: panel_control.ensure_panel_logic(bot, g, app_db, force_create_channel)

# --- Events ---

@bot.event
async def on_ready():
    # Initialize Global HTTP Session
    if state.http_session is None or state.http_session.closed:
        state.http_session = aiohttp.ClientSession()
        print("✅ Global HTTP Session initialized")

    # 0. Sync Owner Info
    if not state.dev_manager.OWNER_IDS:
        app_info = await bot.application_info()
        if app_info.team:
            for member in app_info.team.members:
                state.dev_manager.OWNER_IDS.add(member.id)
        else:
            state.dev_manager.OWNER_IDS.add(app_info.owner.id)
    
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
        "bot_app.cogs.shop",
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

import signal

# --- Entry Point ---

async def shutdown_handler(signal_type):
    print(f"\n🛑 Received {signal_type}. Starting graceful shutdown...")
    
    # 1. Stop all Voice Loggers (flushes current buffers to worker)
    if hasattr(bot, 'loggers'):
        print(f"   Stopping {len(bot.loggers)} active loggers...")
        # Use gather to stop parallel
        await asyncio.gather(*[l.stop() for l in bot.loggers.values()])
    
    # 2. Wait for Workers to finish queue
    if hasattr(bot, 'loggers'):
        print("   Waiting for processors to finish pending jobs (this may take time)...")
        # We need to run this in a thread executor because join() blocks
        loop = asyncio.get_running_loop()
        for l in bot.loggers.values():
            if hasattr(l, 'processor'):
                await loop.run_in_executor(None, l.processor.join)
    
    # 3. Close DB
    if hasattr(bot, 'db'):
        print("   Closing Database...")
        await bot.db.close()

    # 4. Close HTTP Session
    if state.http_session and not state.http_session.closed:
        print("   Closing HTTP Session...")
        await state.http_session.close()
        
    print("👋 Graceful shutdown complete. Bye!")
    # Force exit to kill daemon threads
    os._exit(0)

async def main():
    # Setup Signal Handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown_handler(s)))
        except NotImplementedError:
            # Windows loop might not support add_signal_handler in some modes, 
            # but usually okay with selector loop.
            pass

    async with bot:
        try:
            await bot.start(TOKEN)
        except KeyboardInterrupt:
            # Fallback if signal handler didn't catch (e.g. Windows sometimes)
            await shutdown_handler("KeyboardInterrupt")
        finally:
            # This block runs if bot.start() returns/errors
            # We already handle shutdown above, but just in case
            pass

def run():
    if not TOKEN: 
        raise RuntimeError("No Token")
    try: 
        if sys.platform == 'win32':
            # Windows specific policy for signals
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        else:
            # Try uvloop on non-Windows
            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
                print("🚀 uvloop active")
            except ImportError:
                print("⚠️ uvloop not installed, using default asyncio loop")

        asyncio.run(main())
    except KeyboardInterrupt: 
        pass

if __name__ == "__main__":
    run()