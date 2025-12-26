import discord
from discord.ext import commands, tasks
from bot_app.core.dev_manager import dev_manager
import logging

logger = logging.getLogger("Progression")

class ProgressionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    @tasks.loop(minutes=10) # Reduced freq to optimize, but logic calculates per minute? No, "every hour" requested.
    # The requirement: "XP issued every hour for time spent".
    # Implementation: Check every minute who is in voice, accumulate local cache, and flush to DB every hour?
    # Simpler: Give small XP every 10 mins (e.g. 10 XP). 
    async def voice_xp_loop(self):
        await self.bot.wait_until_ready()
        # XP Amount for 10 mins of voice
        XP_PER_TICK = 50 

        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if not channel.members: continue
                # Ignore AFK channels usually
                if guild.afk_channel and channel.id == guild.afk_channel.id:
                    continue
                
                # Filter active members (not bots, not deafened if strict)
                active_members = [m for m in channel.members if not m.bot and not m.voice.self_deaf]
                
                # If only 1 person, maybe don't give XP (farming alone)? Let's allow it for now.
                if len(active_members) > 0:
                    for m in active_members:
                        # Dev God Mode gets double? Or standard.
                        amount = XP_PER_TICK
                        if dev_manager.is_god_mode(m.id):
                            amount *= 2 # Bonus for testing
                        
                        # BUFF CHECK: XP Boost
                        if hasattr(self.bot, 'buff_manager'):
                            mult = await self.bot.buff_manager.get_buff_value(guild.id, m.id, "xp_boost", default=1.0)
                            if mult > 1.0:
                                amount = int(amount * mult)
                        
                        await self.bot.db.add_xp_and_words(guild.id, m.id, amount, 0, 0)

    # --- Rating Logic (Placeholder for "Real Metrics") ---
    # Can be called periodically or on specific events
    async def recalculate_rating(self, guild_id, user_id):
        # Example formula: Activity + Wealth + Social
        pass

    @commands.command(name="reset_progression", hidden=True)
    async def cmd_reset_xp(self, ctx):
        if not dev_manager.is_god_mode(ctx.author.id):
            return
        
        await self.bot.db.reset_xp_keep_level(ctx.guild.id)
        await ctx.send("✅ XP сброшен для всего сервера (уровни сохранены визуально, но прогресс 0).")

async def setup(bot):
    await bot.add_cog(ProgressionCog(bot))
