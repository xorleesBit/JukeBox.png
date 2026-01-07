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
from logging.handlers import TimedRotatingFileHandler

log_dir = "logs/console"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "bot.log")

logging.basicConfig(
    level=logging.WARNING, # Default: Only Warnings and Errors
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Exception: We want to see Played Phrases (INFO)
logging.getLogger("bot_app.features.prank_manager").setLevel(logging.INFO)

# Silence noisy loggers (Double check)
for lib in ["discord.ext.voice_recv.reader", "discord.ext.voice_recv.rtp", "discord.ext.voice_recv.opus", "httpx", "discord.gateway"]:
    logging.getLogger(lib).setLevel(logging.ERROR)

# Suppress CryptoError spam (external lib issue)
logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.CRITICAL)

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
    # Setup Audio
    audio_setup.setup_audio_libraries()
    
    import discord.opus
    print(f"🔊 Opus Loaded: {discord.opus.is_loaded()}")
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

    async def handle_get_commands(request):
        cmds = []
        for cmd in bot.commands:
            cmds.append({
                "name": cmd.name,
                "aliases": cmd.aliases,
                "cog": cmd.cog_name,
                "enabled": cmd.enabled
            })
        return web.json_response(cmds)

    async def handle_toggle_command(request):
        data = await request.json()
        cmd_name = data.get('name')
        enable = data.get('enabled')
        cmd = bot.get_command(cmd_name)
        if cmd:
            cmd.enabled = enable
            return web.json_response({"status": "ok", "enabled": cmd.enabled})
        return web.json_response({"error": "Command not found"}, status=404)

    async def handle_get_settings(request):
        gid = int(request.query.get('guild_id', 0))
        if not gid: return web.json_response({})
        settings = await state.get_settings(gid)
        return web.json_response(settings._cache if hasattr(settings, '_cache') else {})

    async def handle_update_settings(request):
        data = await request.json()
        gid = int(data.get('guild_id', 0))
        key = data.get('key')
        val = data.get('value')
        settings = await state.get_settings(gid)
        if isinstance(val, bool): settings.set_bool(key, val)
        elif isinstance(val, int): settings.set_int(key, val)
        else: settings.set_string(key, str(val))
        return web.json_response({"status": "ok"})

    async def handle_update_user(request):
        data = await request.json()
        gid, uid = data.get('guild_id'), data.get('user_id')
        if 'balance' in data:
            await bot.db.pool.execute("UPDATE users SET balance = $1 WHERE guild_id = $2 AND user_id = $3", data['balance'], gid, uid)
        if 'xp' in data:
            await bot.db.pool.execute("UPDATE users SET xp = $1 WHERE guild_id = $2 AND user_id = $3", data['xp'], gid, uid)
        return web.json_response({"status": "ok"})

    async def handle_get_users(request):
        guild_id = int(request.query.get('guild_id', 0))
        if not guild_id: return web.json_response({"error": "No guild_id"}, status=400)
        
        # Get raw DB data
        users = await bot.db.get_top_users(guild_id, limit=100)
        
        # Enrich with Discord Data
        guild = bot.get_guild(guild_id)
        enriched = []
        for u in users:
            u_dict = dict(u)
            if guild:
                member = guild.get_member(u['user_id'])
                if member:
                    u_dict['name'] = member.name
                    u_dict['display_name'] = member.display_name
                    u_dict['avatar'] = str(member.display_avatar.url) if member.display_avatar else None
                else:
                    u_dict['name'] = "Unknown"
                    u_dict['display_name'] = "Left Server"
            enriched.append(u_dict)
            
        return web.json_response(enriched)

    # --- Flow Management Endpoints ---
    async def handle_list_flows(request):
        flows_dir = "/app/data/flows"
        if not os.path.exists(flows_dir): return web.json_response([])
        files = [f for f in os.listdir(flows_dir) if f.endswith('.json')]
        return web.json_response(files)

    async def handle_get_flow(request):
        name = request.query.get('name')
        if not name: return web.json_response({"error": "No name"}, status=400)
        path = f"/app/data/flows/{name}"
        if not os.path.exists(path): return web.json_response({"error": "Not found"}, status=404)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return web.json_response(json.load(f))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_test_node(request):
        try:
            req = await request.json()
            node_type = req.get('type')
            data = req.get('data', {})
            # Frontend can send previous context to resolve variables
            mock_context = req.get('context', {})
            
            # Default Mock Trigger if empty
            if "trigger" not in mock_context:
                mock_context["trigger"] = {
                    "message": {
                        "content": "Test Message Content",
                        "author": {"name": "TestUser", "display_name": "Test User"},
                        "id": 123456789
                    }
                }

            # Use Interpreter's logic to resolve variables
            interpreter = getattr(bot, 'flow_interpreter', None)
            if not interpreter:
                interpreter = FlowInterpreter(bot, app_db) # Fallback
            
            resolved_data = interpreter._resolve_params(data, mock_context)
            
            result = {"success": True, "output": None, "logs": [], "resolved_inputs": resolved_data}
            
            if node_type == 'action_ai' or node_type == 'action_ai_response':
                prompt = resolved_data.get('prompt') or resolved_data.get('system_prompt', '')
                from bot_app.integrations.ai_client import ask_ai
                # Simulate
                logs = []
                try:
                    resp = await ask_ai(f"System: {prompt}\nUser: {mock_context['trigger']['message']['content']}")
                    result['output'] = {"response": resp}
                except Exception as e:
                    result['output'] = {"error": str(e)}
                
            elif node_type == 'trigger':
                f = resolved_data.get('filters', {}).get('content_contains', '')
                result['output'] = {"message": mock_context['trigger']['message']} # Pass-through
                
            elif node_type == 'action_reply':
                result['output'] = {"sent_content": resolved_data.get('text')}
                
            elif node_type == 'action_delay':
                result['output'] = {"slept": resolved_data.get('seconds')}
                
            elif node_type == 'action_role':
                rid = resolved_data.get('role_id')
                result['output'] = {"role_id": rid, "status": "Simulated (Role add)"}
                
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)})

    app = web.Application()
    app.router.add_get('/reload', handle_reload)
    app.router.add_get('/stats', handle_stats)
    app.router.add_get('/guilds', handle_get_guilds)
    app.router.add_get('/commands', handle_get_commands)
    app.router.add_post('/commands/toggle', handle_toggle_command)
    app.router.add_get('/settings', handle_get_settings)
    app.router.add_post('/settings/update', handle_update_settings)
    app.router.add_get('/db/users', handle_get_users)
    app.router.add_post('/db/users/update', handle_update_user)
    
    app.router.add_get('/flows/list', handle_list_flows)
    app.router.add_get('/flows/get', handle_get_flow)
    app.router.add_post('/nodes/test', handle_test_node)
    
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

    # Start Sidecar API immediately so panel can connect even if bot is connecting
    asyncio.create_task(start_sidecar_api(bot))

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