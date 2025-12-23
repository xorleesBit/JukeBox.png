import discord
from discord.ext import commands, tasks
import time
import re
from bot_app.core.dev_manager import dev_manager

class UtilitiesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.remind_loop.start()

    def cog_unload(self):
        self.remind_loop.cancel()

    # --- AFK System ---
    @commands.command(name="afk")
    async def afk_cmd(self, ctx, *, message="AFK"):
        await self.bot.db.set_afk(ctx.author.id, ctx.guild.id, message)
        # Check if nick already has [AFK]
        display_name = ctx.author.display_name
        if not display_name.startswith("[AFK]"):
            try:
                await ctx.author.edit(nick=f"[AFK] {display_name}"[:32])
            except: pass
        
        await ctx.send(f"💤 {ctx.author.mention} ушел в AFK: {message}", delete_after=10)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        # 1. Check if author was AFK -> remove AFK
        afk_data = await self.bot.db.get_afk(message.author.id)
        if afk_data:
            await self.bot.db.remove_afk(message.author.id)
            if message.author.display_name.startswith("[AFK] "):
                new_nick = message.author.display_name[6:]
                try: await message.author.edit(nick=new_nick)
                except: pass
            await message.channel.send(f"👋 С возвращением, {message.author.mention}!", delete_after=5)

        # 2. Check if mentioned user is AFK
        if message.mentions:
            for user in message.mentions:
                afk_target = await self.bot.db.get_afk(user.id)
                if afk_target:
                    msg, since = afk_target['message'], afk_target['since_ts']
                    mins = int((time.time() - since) / 60)
                    await message.channel.send(f"💤 **{user.display_name}** сейчас AFK ({mins} мин): {msg}", delete_after=10)

    # --- Remind Me ---
    @commands.command(name="remindme")
    async def remind_cmd(self, ctx, time_str: str, *, text: str):
        """Format: 10m, 1h, 2d"""
        seconds = 0
        match = re.match(r"(\d+)([mhd])", time_str.lower())
        if match:
            val = int(match.group(1))
            unit = match.group(2)
            if unit == 'm': seconds = val * 60
            elif unit == 'h': seconds = val * 3600
            elif unit == 'd': seconds = val * 86400
        else:
            return await ctx.send("❌ Неверный формат. Используйте: 10m, 1h, 1d", delete_after=5)

        due_ts = time.time() + seconds
        await self.bot.db.add_reminder(ctx.author.id, ctx.channel.id, due_ts, text)
        await ctx.send(f"⏰ Напоминание установлено через {time_str}: \"{text}\"", delete_after=5)

    @tasks.loop(seconds=30)
    async def remind_loop(self):
        try:
            now = time.time()
            reminders = await self.bot.db.get_pending_reminders(now)
            for r in reminders:
                rid, uid, cid, txt, due = r['remind_id'], r['user_id'], r['channel_id'], r['text'], r['due_ts']
                
                channel = self.bot.get_channel(cid)
                if channel:
                    try:
                        await channel.send(f"⏰ <@{uid}> Напоминание: **{txt}**")
                    except: pass
                
                await self.bot.db.complete_reminder(rid)
        except Exception as e:
            print(f"Remind loop error: {e}")

    @remind_loop.before_loop
    async def before_remind(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(UtilitiesCog(bot))