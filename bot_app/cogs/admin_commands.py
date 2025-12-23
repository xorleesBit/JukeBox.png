import discord
import os
import shutil
import logging
from discord.ext import commands
from bot_app.core.config import PHRASES_DIR

logger = logging.getLogger(__name__)

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.loggers = bot.loggers

    async def ensure_panel(self, guild, force=False):
        # This calls the logic in bot_entry.py ideally, but we can't import main.
        # So we invoke the global App logic if available, or duplicate simply.
        # Since bot_entry has the logic, we will keep panel management there mostly, 
        # or expose a method on the bot object. 
        # For now, let's assume bot has a helper or we trigger the event.
        # We can trigger on_guild_join manually? No.
        # Let's just use the existing command logic but in Cog.
        pass # Panel logic is complex and tied to App class in bot_entry. Let's keep panel cmds in bot_entry for now or refactor App later.

    @commands.command(name="setup_panel")
    @commands.has_permissions(administrator=True)
    async def cmd_setup_panel(self, ctx):
        # We'll rely on the main bot to have 'ensure_panel' attached or injected.
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
            # await ctx.message.delete() - handled by global on_message
        else:
            await ctx.send("Функция недоступна.", delete_after=5)

    @commands.command(name="delete_all_phrases")
    @commands.has_permissions(administrator=True)
    async def cmd_delete_all_phrases(self, ctx):
        confirm_msg = await ctx.send("⚠️ **Удалить ВСЕ пранки?** (Напишите `confirm`)")
        def check(m): return m.author == ctx.author and m.content == "confirm"
        try: await self.bot.wait_for("message", check=check, timeout=15)
        except: return await ctx.send("Отмена.", delete_after=5)
        
        await self.db.pool.execute("DELETE FROM prank_phrases WHERE guild_id=$1", ctx.guild.id)
        guild_dir = os.path.join(PHRASES_DIR, str(ctx.guild.id))
        if os.path.exists(guild_dir):
            try: shutil.rmtree(guild_dir)
            except: pass
        await ctx.send("✅ Все удалено.", delete_after=5)

    @commands.command(name="play_random")
    @commands.has_permissions(administrator=True)
    async def cmd_play_random(self, ctx):
        logger = self.loggers.get(ctx.guild.id)
        if logger and logger.prank:
            await logger.prank.play_random()
        else:
            await ctx.send("Логгер выключен.", delete_after=5)

    @commands.command(name="reset_all_achs")
    @commands.has_permissions(administrator=True)
    async def cmd_reset_all_achs(self, ctx):
        msg = await ctx.send(embed=discord.Embed(description="⚠️ **Вы уверены, что хотите удалить ВСЕ достижения у ВСЕХ пользователей?**\nНапишите `confirm` для подтверждения.", color=discord.Color.red()))
        
        def check(m): return m.author == ctx.author and m.content == "confirm" and m.channel == ctx.channel
        
        try:
            await self.bot.wait_for("message", check=check, timeout=15)
        except:
            return await ctx.send(embed=discord.Embed(description="Отмена (таймаут).", color=discord.Color.greyple()), delete_after=5)
        
        await self.db.reset_all_achievements(ctx.guild.id)
        await ctx.send(embed=discord.Embed(description="✅ Все достижения удалены.", color=discord.Color.green()))

    @commands.command(name="debug")
    @commands.has_permissions(administrator=True)
    async def cmd_debug(self, ctx):
        l = self.loggers.get(ctx.guild.id)
        msg = f"**Debug**\nGuild: {ctx.guild.id}\nLogger: {'ACTIVE' if l else 'NONE'}\n"
        if l:
            msg += f"Rec: {l.is_recording}\nPrank: {'OK' if l.prank else 'NO'}\n"
        await ctx.send(msg, delete_after=20)

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))