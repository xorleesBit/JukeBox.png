import discord
from discord.ext import commands
import time
import asyncio
import logging
from bot_app.core.state import loggers, user_spam_cooldowns, db

logger = logging.getLogger(__name__)

class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        # 1. Flow Execution (Graph Engine)
        if hasattr(self.bot, 'flow_interpreter'):
            # Определяем тип триггера на основе контекста сообщения
            if message.guild:
                # Триггер для сообщений на сервере
                await self.bot.flow_interpreter.handle_event("on_message_guild", {"message": message})
            else:
                # Триггер для личных сообщений
                await self.bot.flow_interpreter.handle_event("on_message_dm", {"message": message})
            
            # Общий триггер (legacy/универсальный)
            await self.bot.flow_interpreter.handle_event("on_message", {"message": message})

        # 2. Command handling (deleting command trigger)
        if message.content.startswith("!"):
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                try: await message.delete()
                except: pass
        
        if not message.guild:
            return

        # 3. XP & Economy Logic
        uid = message.author.id
        now = time.time()
        if now - user_spam_cooldowns.get(uid, 0) > 2.0:
            user_spam_cooldowns[uid] = now
            words = message.content.split()
            if words and db:
                await db.upsert_user(message.guild.id, uid, message.author.display_name)
                await db.add_xp_and_words(message.guild.id, uid, min(len(words), 20), w_text=len(words), w_audio=0, words_list=words)
        
        # 4. Chat Logging (to archive/txt)
        l = loggers.get(message.guild.id)
        if l and l.is_recording:
            l.log_chat_message(message.author.name, message.content)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Триггер на вход нового участника."""
        if hasattr(self.bot, 'flow_interpreter'):
            await self.bot.flow_interpreter.handle_event("on_member_join", {"member": member, "guild": member.guild})

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.guild: return
        
        # Интеграция с интерпретатором (триггер входа в голос)
        if hasattr(self.bot, 'flow_interpreter') and after.channel and not before.channel:
            await self.bot.flow_interpreter.handle_event("on_voice_join", {"member": member, "channel": after.channel})

        if hasattr(self.bot, 'context_manager') and after.channel:
             await self.bot.context_manager.update_presence(member.guild, after.channel)
        
        l = loggers.get(member.guild.id)
        if not l or not l.is_recording: return
        
        if member.id == self.bot.user.id:
            if not after.channel:
                # Potential 1006 disconnect. Wait a bit to see if it's a transient state or reconnecting.
                await asyncio.sleep(15)
                # Check again. If still disconnected and we haven't started stopping intentionally:
                # Refresh member to ensure cache is up to date
                try:
                    m = member.guild.get_member(member.id)
                    if m: member = m
                except: pass

                if not member.voice or not member.voice.channel:
                    if l.is_recording and l.state != "stopping":
                        l.log_event(time.time(), "🛑", "Бот отключен от канала (не удалось переподключиться за 15с).")
                        await l.stop()
                return
            if before.channel and after.channel and before.channel.id != after.channel.id:
                l.voice_channel_id = after.channel.id
                l.log_event(time.time(), "🔄", f"Бот перемещен в канал: {after.channel.name}")
                return

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
        if hasattr(self.bot, 'context_manager') and after.voice and after.voice.channel:
             await self.bot.context_manager.update_presence(after.guild, after.voice.channel)
             
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