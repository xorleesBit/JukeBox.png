import discord
import os
import shutil
import logging
import re
import datetime
from discord.ext import commands
from bot_app.core.config import PHRASES_DIR, LOG_DIR

logger = logging.getLogger(__name__)

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.loggers = bot.loggers

    @commands.command(name="setup_panel")
    @commands.has_permissions(administrator=True)
    async def cmd_setup_panel(self, ctx):
        if hasattr(self.bot, 'ensure_panel_func'):
            await self.bot.ensure_panel_func(ctx.guild, force_create_channel=True)
            await ctx.send("Панель пересоздана.", delete_after=5)
        else:
            await ctx.send("Функция недоступна.", delete_after=5)

    @commands.command(name="panel")
    @commands.has_permissions(administrator=True)
    async def cmd_panel_refresh(self, ctx):
        if hasattr(self.bot, 'ensure_panel_func'):
            await self.bot.ensure_panel_func(ctx.guild, force_create_channel=False)
        else:
            await ctx.send("Функция недоступна.", delete_after=5)

    @commands.command(name="delete_all_phrases")
    @commands.has_permissions(administrator=True)
    async def cmd_delete_all_phrases(self, ctx):
        # Initial user command is auto-deleted by on_message usually, but check
        confirm_msg = await ctx.send("⚠️ **Удалить ВСЕ пранки?** (Напишите `confirm`)")
        
        def check(m): return m.author == ctx.author and m.content == "confirm" and m.channel == ctx.channel
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=15)
            await msg.delete() # Delete user's confirm
        except:
            await confirm_msg.delete()
            return await ctx.send("Отмена.", delete_after=5)
        
        await confirm_msg.delete()
        await self.db.pool.execute("DELETE FROM prank_phrases WHERE guild_id=$1", ctx.guild.id)
        guild_dir = os.path.join(PHRASES_DIR, str(ctx.guild.id))
        if os.path.exists(guild_dir):
            try: shutil.rmtree(guild_dir)
            except: pass
        await ctx.send("✅ Все удалено.", delete_after=5)

    @commands.command(name="reset_all_achs")
    @commands.has_permissions(administrator=True)
    async def cmd_reset_all_achs(self, ctx):
        confirm_msg = await ctx.send(embed=discord.Embed(description="⚠️ **Сбросить ВСЕ ачивки?**\nНапишите `confirm`.", color=discord.Color.red()))
        
        def check(m): return m.author == ctx.author and m.content == "confirm" and m.channel == ctx.channel
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=15)
            await msg.delete()
        except:
            await confirm_msg.delete()
            return await ctx.send(embed=discord.Embed(description="Отмена.", color=discord.Color.greyple()), delete_after=5)
        
        await confirm_msg.delete()
        await self.db.reset_all_achievements(ctx.guild.id)
        await ctx.send(embed=discord.Embed(description="✅ Все достижения удалены.", color=discord.Color.green()), delete_after=5)

    @commands.command(name="play_random")
    @commands.has_permissions(administrator=True)
    async def cmd_play_random(self, ctx):
        logger = self.loggers.get(ctx.guild.id)
        if logger and logger.prank:
            await logger.prank.play_random()
        else:
            await ctx.send("Логгер выключен.", delete_after=5)

    @commands.command(name="debug")
    @commands.has_permissions(administrator=True)
    async def cmd_debug(self, ctx):
        l = self.loggers.get(ctx.guild.id)
        msg = f"**Debug**\nGuild: {ctx.guild.id}\nLogger: {'ACTIVE' if l else 'NONE'}\n"
        if l:
            msg += f"Rec: {l.is_recording}\nPrank: {'OK' if l.prank else 'NO'}\n"
        await ctx.send(msg, delete_after=20)

    @commands.command(name="migrate_logs_msc")
    @commands.has_permissions(administrator=True)
    async def cmd_migrate_logs(self, ctx):
        """Adds +3 hours to all timestamps in logs."""
        status = await ctx.send("⏳ Начинаю миграцию времени...")
        count = 0
        
        # Regex for [HH:MM:SS]
        time_re = re.compile(r"^\\[(\d{2}:\d{2}:\d{2})\\]")
        
        for root, dirs, files in os.walk(LOG_DIR):
            for file in files:
                if file.endswith(".log") and not file.endswith(".events.log"):
                    path = os.path.join(root, file)
                    new_lines = []
                    modified = False
                    
                    try:
                        with open(path, "r", encoding="utf-8-sig") as f:
                            lines = f.readlines()
                        
                        for line in lines:
                            match = time_re.match(line)
                            if match:
                                t_str = match.group(1)
                                try:
                                    # Parse -> Add 3h -> Format
                                    dt = datetime.datetime.strptime(t_str, "%H:%M:%S")
                                    new_dt = dt + datetime.timedelta(hours=3)
                                    new_t_str = new_dt.strftime("%H:%M:%S")
                                    line = line.replace(f"[{t_str}]", f"[{new_t_str}]", 1)
                                    modified = True
                                except: pass
                            new_lines.append(line)
                        
                        if modified:
                            with open(path, "w", encoding="utf-8-sig") as f:
                                f.writelines(new_lines)
                            count += 1
                    except Exception as e:
                        logger.error(f"Error migrating {path}: {e}")

        await status.edit(content=f"✅ Миграция завершена. Обновлено файлов: {count}")

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))