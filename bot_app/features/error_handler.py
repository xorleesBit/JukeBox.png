import os
import sys
import traceback
import datetime
import logging
import discord
from discord.ext import commands
from bot_app.core.config import PROJECT_DIR
from bot_app.ui.common import send_error, send_warning

LOGS_DIR = os.path.join(PROJECT_DIR, "logs", "errors")

def ensure_log_dir():
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR, exist_ok=True)

# --- Legacy / Standalone Helpers (Used by Debug Menu) ---

def get_log_files() -> list[str]:
    """Returns sorted list of error log files."""
    ensure_log_dir()
    return sorted([f for f in os.listdir(LOGS_DIR) if f.endswith(".log")], reverse=True)

def read_log_segment(filename: str, lines=50) -> str:
    """Reads the last N lines of a log file."""
    path = os.path.join(LOGS_DIR, filename)
    if not os.path.exists(path):
        return "File not found."
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.readlines()
            return "".join(content[-lines:])
    except Exception as e:
        return f"Error reading file: {e}"

def log_error(exception: Exception, ctx_info: str = ""):
    """Legacy wrapper to log error manually."""
    ensure_log_dir()
    now = datetime.datetime.now()
    filename = now.strftime("%Y-%m-%d.log")
    filepath = os.path.join(LOGS_DIR, filename)
    
    tb_str = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    
    entry = f"[{now.strftime('%H:%M:%S')}] {ctx_info}\n{tb_str}\n{'-'*40}\n"
    
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print(f"CRITICAL: Failed to write to error log: {e}")

# --- Cog Implementation ---

class GlobalErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        ensure_log_dir()

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """The event triggered when an error is raised while invoking a command."""
        
        # If the command has its own error handler, ignore this one
        if hasattr(ctx.command, 'on_error'):
            return

        # Get the original exception if it exists
        error = getattr(error, 'original', error)

        # Ignored errors
        if isinstance(error, commands.CommandNotFound):
            return # Just ignore unknown commands to avoid spam

        if isinstance(error, commands.DisabledCommand):
            return await send_warning(ctx, "Эта команда временно отключена.")

        if isinstance(error, commands.NoPrivateMessage):
            return await send_warning(ctx, "Эта команда не работает в личных сообщениях.")

        # User Input Errors
        if isinstance(error, commands.MissingRequiredArgument):
            return await send_error(ctx, f"Пропущен обязательный аргумент: `{error.param.name}`\nИспользование: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`")

        if isinstance(error, commands.BadArgument):
            return await send_error(ctx, "Передан неверный аргумент. Проверьте правильность ввода.")

        # Permissions
        if isinstance(error, commands.NotOwner):
            return await send_error(ctx, "Эта команда доступна только разработчику бота.")

        if isinstance(error, commands.MissingPermissions):
            missing = ", ".join(error.missing_permissions)
            return await send_error(ctx, f"У вас нет прав для выполнения этой команды.\nТребуется: `{missing}`")

        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            return await send_error(ctx, f"У меня нет прав для выполнения этого действия.\nТребуется: `{missing}`")
        
        if isinstance(error, commands.CommandOnCooldown):
             return await send_warning(ctx, f"Подождите {error.retry_after:.1f} сек.", title="Кулдаун")

        # Custom Checks
        if isinstance(error, commands.CheckFailure):
            return await send_warning(ctx, "Вы не можете использовать эту команду (не выполнено условие проверки).")

        # Generic / Critical Errors
        # Log to file and notify user
        self.log_exception(error, ctx)
        await send_error(ctx, f"Произошла внутренняя ошибка при выполнении команды.\nРазработчики уведомлены.\nОшибка: `{str(error)}`")

    def log_exception(self, exception: Exception, ctx):
        command_name = ctx.command.qualified_name if ctx.command else "Unknown"
        user_info = f"{ctx.author} ({ctx.author.id})"
        guild_info = f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else "DM"
        
        ctx_info = f"CMD: {command_name} | User: {user_info} | Loc: {guild_info} | Content: {ctx.message.content}"
        
        # Use common logger function
        log_error(exception, ctx_info)
        print(f"[ERROR] Logged exception for {command_name}")

async def setup(bot):
    await bot.add_cog(GlobalErrorHandler(bot))