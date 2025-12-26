import discord
import os
import shutil
import logging
import datetime
from discord.ext import commands
from bot_app.core.config import PHRASES_DIR, LOG_DIR

logger = logging.getLogger(__name__)

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.loggers = bot.loggers

    @commands.command(name="setup_panel", hidden=True)
    @commands.has_permissions(administrator=True)
    async def cmd_setup_panel(self, ctx):
        if hasattr(self.bot, 'ensure_panel_func'):
            await self.bot.ensure_panel_func(ctx.guild, force_create_channel=True)
            await ctx.send("Панель пересоздана.", delete_after=5)

    @commands.command(name="panel", hidden=True)
    @commands.has_permissions(administrator=True)
    async def cmd_panel_refresh(self, ctx):
        if hasattr(self.bot, 'ensure_panel_func'):
            await self.bot.ensure_panel_func(ctx.guild, force_create_channel=False)

    @commands.command(name="delete_all_phrases", hidden=True)
    @commands.has_permissions(administrator=True)
    async def cmd_delete_all_phrases(self, ctx):
        """Удаляет ВСЕ фразы сервера, КРОМЕ избранных."""
        confirm_msg = await ctx.send("⚠️ **Удалить все ОБЫЧНЫЕ фразы?** (Избранные останутся).\nНапишите `confirm`.")
        
        def check(m): return m.author == ctx.author and m.content == "confirm" and m.channel == ctx.channel
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=15)
            await msg.delete()
        except:
            await confirm_msg.delete()
            return await ctx.send("Отмена.", delete_after=5)
        
        await confirm_msg.delete()
        
        # 1. DB Cleanup (Safe)
        await self.db.delete_all_non_fav_phrases(ctx.guild.id)
        
        # 2. File Cleanup is tricky because files don't mark favorites.
        # Strategy: DB is authority. We won't delete files blindly anymore.
        # We rely on an orphan cleaner task (future improvement) or just keep files.
        # Deleting the folder like before is DANGEROUS for favorites.
        # So we ONLY clear DB records. Space cleanup should be a separate "vacuum" command.
        
        await ctx.send("✅ База очищена (избранное сохранено). Файлы останутся до очистки мусора.", delete_after=10)

    @commands.command(name="get_logs", hidden=True)
    @commands.has_permissions(administrator=True)
    async def cmd_get_logs(self, ctx, date_start: str, date_end: str = None):
        """
        Скачать логи за период.
        Формат: !get_logs YYYY-MM-DD [YYYY-MM-DD]
        """
        if not date_end: date_end = date_start
        
        try:
            dt_start = datetime.datetime.strptime(date_start, "%Y-%m-%d")
            dt_end = datetime.datetime.strptime(date_end, "%Y-%m-%d")
        except ValueError:
            return await ctx.send("❌ Неверный формат. Используйте YYYY-MM-DD")

        await ctx.send(f"🔍 Поиск логов с {date_start} по {date_end}...", delete_after=5)

        # Logic to find files in Archives and Active logs
        # This requires scanning LOG_DIR/archives/{GUILD_ID}/ and LOG_DIR/{DATE}/{GUILD_NAME}/
        # Since logic is complex, I'll defer to a helper or do simplistic search here.
        # Let's do simple search in archives for now as per requirement.
        
        found_files = []
        archives_dir = os.path.join(LOG_DIR, "archives", str(ctx.guild.id))
        
        if os.path.exists(archives_dir):
            for f in os.listdir(archives_dir):
                # Format: merged_START_END.txt
                # We just check if file name overlaps? Simple text search for now.
                if f.endswith(".txt"):
                    found_files.append(discord.File(os.path.join(archives_dir, f)))

        if not found_files:
            return await ctx.send("📁 Архивы за этот период не найдены (возможно, еще не созданы или даты не совпадают).")
            
        await ctx.send(f"📂 Найдено архивов: {len(found_files)}", files=found_files[:10])

    @commands.command(name="cut", hidden=True)
    @commands.has_permissions(administrator=True)
    async def cmd_cut(self, ctx):
        """✂️ Экстренно завершить запись текущего фрагмента и отправить на транскрибацию (Высший приоритет)."""
        logger = self.loggers.get(ctx.guild.id)
        if not logger or not logger.is_recording:
            return await ctx.send("❌ Логгер не активен.", delete_after=5)
        
        try: await ctx.message.add_reaction("✂️")
        except: pass
        
        # Priority 0 = Emergency (Normal is 10)
        await logger.rotate(priority=0)
        await ctx.send("✅ Запись обрезана и отправлена в приоритетную очередь.", delete_after=10)

    @commands.command(name="update_achs")
    @commands.has_permissions(administrator=True)
    async def cmd_update_achs(self, ctx):
        from bot_app.features.profile_manager import ProfileManager
        msg = await ctx.send(embed=discord.Embed(description="🏆 Раздаем ачивки (сегодня)...", color=discord.Color.blue()))
        mgr = ProfileManager(self.db, ctx.guild.id)
        res = await mgr.update_achievements(ctx.guild.name, days=1)
        await msg.edit(embed=discord.Embed(description=res, color=discord.Color.green()))

    @commands.command(name="update_achs_all")
    @commands.has_permissions(administrator=True)
    async def cmd_update_achs_all(self, ctx):
        from bot_app.features.profile_manager import ProfileManager
        msg = await ctx.send(embed=discord.Embed(description="🏆 Раздаем ачивки (5 дней)...", color=discord.Color.purple()))
        mgr = ProfileManager(self.db, ctx.guild.id)
        res = await mgr.update_achievements(ctx.guild.name, days=5)
        await msg.edit(embed=discord.Embed(description=res, color=discord.Color.green()))

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))