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

# New optimized imports
from .core.http_pool import HTTPSessionPool
from .core.rate_limiter import APIRateLimiter
from .features.memory_monitor import MemoryMonitor
from .core.metrics import collect_metrics, format_metrics
from .features.profile_manager import ProfileManager
from .features.context_manager import ContextManager
from .features.ai_manager import AIManager
from .features.flow_interpreter import FlowInterpreter

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

# HTTP Session Pool
http_pool = HTTPSessionPool(max_connections_per_host=10, total_connections=100)

# Rate Limiters for APIs
azure_rate_limiter = APIRateLimiter(max_requests=15, time_window=1.0, name="Azure_STT")
assembly_rate_limiter = APIRateLimiter(max_requests=10, time_window=1.0, name="Assembly_STT")

# Memory Monitor
memory_monitor = MemoryMonitor(warning_threshold_mb=1024, critical_threshold_mb=2048)

# Initialize Features
profile_manager = ProfileManager(app_db)
context_manager = ContextManager(bot)
ai_manager = AIManager(app_db)

# Inject Global State
state.db = app_db
state.profile_manager = profile_manager
state.context_manager = context_manager
state.ai_manager = ai_manager

bot.db = app_db
bot.loggers = state.loggers
bot.http_pool = http_pool
bot.azure_rate_limiter = azure_rate_limiter
bot.assembly_rate_limiter = assembly_rate_limiter
bot.memory_monitor = memory_monitor
bot.profile_manager = profile_manager
bot.context_manager = context_manager
bot.ai_manager = ai_manager

# Helper lambda to match old interface if cogs use it
bot.get_settings = state.get_settings
# Inject panel logic for reuse if needed (though it's better to import)
bot.ensure_panel_func = lambda g, force_create_channel=False: panel_control.ensure_panel_logic(bot, g, app_db, force_create_channel)

# --- Events ---

@bot.event
async def on_ready():
    import discord.opus
    print(f"🔊 Opus Loaded: {discord.opus.is_loaded()}")

    # Initialize Global HTTP Session from pool
    if state.http_session is None or state.http_session.closed:
        state.http_session = await http_pool.get_session()
        print("✅ Global HTTP Session initialized")
    
    # Start Memory Monitor
    memory_monitor.start()
    print("✅ Memory Monitor started")

    # Load AI Config
    if state.ai_manager:
        await state.ai_manager.load()
        print(f"✅ AI Config loaded: {state.ai_manager.current_provider}")

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
        # Connect DB with dynamic pool sizing
        servers_count = len(bot.guilds)
        await app_db.connect(servers_count=servers_count)
        print(f"✅ Database Connected (optimized for {servers_count} servers)")
        
        # Initialize Flow Interpreter
        bot.flow_interpreter = FlowInterpreter(bot, app_db)
        print("✅ Flow Interpreter initialized")
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return

    # Load Cogs
    initial_extensions = [
        "bot_app.features.error_handler", # Global Error Handler
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
        "bot_app.cogs.games",
        "bot_app.cogs.help", # Custom Help
    ]

    for ext in initial_extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Loaded {ext}")
        except Exception as e:
            print(f"❌ Failed to load {ext}: {e}")

    # Setup Audio
    audio_setup.setup_audio_libraries()
    
    # Configure STT rate limiters
    from bot_app.integrations.stt_async import set_rate_limiters
    set_rate_limiters(azure_rate_limiter, assembly_rate_limiter)
    print("✅ STT rate limiters configured")
    
    # Start Log Archiver
    from bot_app.features.log_archiver import LogArchiver
    bot.archiver = LogArchiver(bot)
    asyncio.create_task(bot.archiver.start())
    
    # Start cache cleanup task
    asyncio.create_task(state.cleanup_expired_caches())
    print("✅ Cache cleanup task started")
    
    # Start metrics logging task
    asyncio.create_task(metrics_logger_task())
    print("✅ Metrics logger started")

    # Start Sidecar API
    asyncio.create_task(start_sidecar_api(bot))
    
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

async def metrics_logger_task():
    """Periodic metrics logging."""
    import logging
    logger = logging.getLogger(__name__)
    
    await asyncio.sleep(60)  # Wait 1 minute before first log
    while True:
        try:
            metrics = await collect_metrics(bot)
            logger.info(f"📊 Metrics: {format_metrics(metrics)}")
            await asyncio.sleep(300)  # Every 5 minutes
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Metrics collection error: {e}")
            await asyncio.sleep(300)

# --- Sidecar API for Panel ---
async def start_sidecar_api(bot):
    from aiohttp import web
    
    async def handle_reload(request):
        if hasattr(bot, 'flow_interpreter'):
            bot.flow_interpreter.load_flows()
            return web.json_response({"status": "ok", "message": "Flows reloaded"})
        return web.json_response({"status": "error", "message": "No interpreter found"}, status=500)

    async def handle_stats(request):
        active_loggers = len(getattr(bot, 'loggers', {}))
        return web.json_response({
            "status": "online",
            "ping": round(bot.latency * 1000) if bot.latency else 0,
            "guilds": len(bot.guilds),
            "active_loggers": active_loggers
        })

    async def handle_get_users(request):
        guild_id = int(request.query.get('guild_id', 0))
        if not guild_id: return web.json_response({"error": "No guild_id"}, status=400)
        users = await bot.db.get_top_users(guild_id, limit=50)
        # Convert to list of dicts if needed
        return web.json_response([dict(u) for u in users])

    async def handle_update_user(request):
        data = await request.json()
        gid, uid = data['guild_id'], data['user_id']
        if 'balance' in data and data['balance'] is not None:
            # We assume a new method in DB or use existing
            await bot.db.pool.execute("UPDATE users SET balance = $1 WHERE guild_id = $2 AND user_id = $3", data['balance'], gid, uid)
        if 'xp' in data and data['xp'] is not None:
            await bot.db.pool.execute("UPDATE users SET xp = $1 WHERE guild_id = $2 AND user_id = $3", data['xp'], gid, uid)
        return web.json_response({"status": "ok"})

    async def handle_get_guilds(request):
        guilds_data = []
        for g in bot.guilds:
            guilds_data.append({
                "id": str(g.id),
                "name": g.name,
                "member_count": g.member_count,
                "icon": g.icon.url if g.icon else None
            })
        return web.json_response(guilds_data)

    app = web.Application()
    app.router.add_get('/reload', handle_reload)
    app.router.add_get('/stats', handle_stats)
    app.router.add_get('/guilds', handle_get_guilds)
    app.router.add_get('/db/users', handle_get_users)
    app.router.add_post('/db/users/update', handle_update_user)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8081)
    await site.start()
    print("🚀 Bot Sidecar API started on port 8081")

import signal

# --- Entry Point ---

async def shutdown_handler(signal_type):
    print(f"\n🛑 Received {signal_type}. Starting graceful shutdown...")
    
    # 1. Stop all Voice Loggers (flushes current buffers to worker)
    if hasattr(bot, 'loggers'):
        print(f"   Stopping {len(bot.loggers)} active loggers...")
        # Use gather to stop parallel
        await asyncio.gather(*[l.stop() for l in bot.loggers.values()], return_exceptions=True)
    
    # 2. Wait for Workers to finish queue (with timeout)
    if hasattr(bot, 'loggers'):
        print("   Waiting for processors to finish pending jobs (max 30s)...")
        loop = asyncio.get_running_loop()
        tasks = []
        for l in bot.loggers.values():
            if hasattr(l, 'processor'):
                l.processor.stop(timeout=30.0)
                tasks.append(loop.run_in_executor(None, l.processor.join, 30.0))
        
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=35.0)
        except asyncio.TimeoutError:
            print("   ⚠️ Some processors did not stop in time")
    
    # 3. Close DB
    if hasattr(bot, 'db'):
        print("   Closing Database...")
        await bot.db.close()
    
    # 4. Close HTTP Pool
    if hasattr(bot, 'http_pool'):
        print("   Closing HTTP Pool...")
        await bot.http_pool.close()
    
    # Also close legacy session if exists
    if state.http_session and not state.http_session.closed:
        await state.http_session.close()
    
    # 5. Stop Memory Monitor
    if hasattr(bot, 'memory_monitor'):
        print("   Stopping Memory Monitor...")
        await bot.memory_monitor.stop()
        
    print("👋 Graceful shutdown complete. Bye!")
    # Force exit to kill daemon threads
    os._exit(0)

async def main(token):
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
            await bot.start(token)
        except KeyboardInterrupt:
            # Fallback if signal handler didn't catch (e.g. Windows sometimes)
            await shutdown_handler("KeyboardInterrupt")
        finally:
            # This block runs if bot.start() returns/errors
            # We already handle shutdown above, but just in case
            pass

def run(debug_mode=False):
    token = os.getenv("DISCORD_BOT_TOKEN_DEBUG") if debug_mode else os.getenv("DISCORD_BOT_TOKEN")
    
    if debug_mode:
        print("🐞 DEBUG MODE ACTIVATED")
        if not token:
            print("❌ DISCORD_BOT_TOKEN_DEBUG not found in .env")
            return
    
    if not token: 
        raise RuntimeError("No Token found")
        
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

        asyncio.run(main(token))
    except KeyboardInterrupt: 
        pass

if __name__ == "__main__":
    run()