import discord
from discord.ext import commands
import time
from bot_app.core.state import loggers, user_spam_cooldowns, db

class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        # 1. Custom command handling logic from original bot_entry
        # 1. Custom command handling logic: Clean up commands if they are valid
        if message.content.startswith("!"):
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                try:
                    await message.delete()
                except Exception:
                    pass
        
        # Note: bot.process_commands(message) is handled by the framework 
        # unless on_message is overridden on the bot instance. 
        # Since this is a listener, we don't need to call it manually 
        # UNLESS we are overriding the main on_message. 
        # However, to be safe and match original logic which might rely on specific order:
        # We will let the default processor handle commands separately.
        
        if not message.guild:
            return

        # 2. XP Logic
        uid = message.author.id
        now = time.time()
        if now - user_spam_cooldowns.get(uid, 0) > 2.0:
            user_spam_cooldowns[uid] = now
            words = message.content.split()
            if words and db:
                await db.upsert_user(message.guild.id, uid, message.author.display_name)
                await db.add_xp_and_words(message.guild.id, uid, min(len(words), 20), w_text=len(words), w_audio=0, words_list=words)
        
        # 3. Logging Logic
        l = loggers.get(message.guild.id)
        if l and l.is_recording:
            l.log_chat_message(message.author.name, message.content)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.guild: return
        l = loggers.get(member.guild.id)
        if not l or not l.is_recording: return
        
        mon_id = l.voice_channel_id
        if after.channel and after.channel.id == mon_id and (not before.channel or before.channel.id != mon_id):
            if member.id != self.bot.user.id:
                l.log_event(time.time(), "🚪", f"{member.name} зашел.")
        elif before.channel and before.channel.id == mon_id and (not after.channel or after.channel.id != mon_id):
            if member.id != self.bot.user.id:
                l.log_event(time.time(), "🚪", f"{member.name} вышел.")

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if not after.guild: return
        logger = loggers.get(after.guild.id)
        if not logger or not logger.is_recording: return
        
        if not after.voice or not after.voice.channel or after.voice.channel.id != logger.voice_channel_id:
            return

        old_acts = {a.name for a in before.activities}
        new_acts = {a.name for a in after.activities}
        started = new_acts - old_acts
        
        ts = time.time()
        for act in started:
            logger.log_event(ts, "🎮", f"{after.name} начал играть в: {act}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        from bot_app.features.panel_control import ensure_panel_logic
        if db:
            await ensure_panel_logic(self.bot, guild, db, force_create_channel=True)

async def setup(bot):
    await bot.add_cog(EventsCog(bot))
