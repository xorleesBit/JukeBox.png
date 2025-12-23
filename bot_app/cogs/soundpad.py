import discord
from discord.ext import commands
import os
import time
from bot_app.core.config import PROJECT_DIR
from bot_app.core.dev_manager import dev_manager
from pydub import AudioSegment

class SoundpadCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sounds_dir = os.path.join(PROJECT_DIR, "voice_logs", "soundpad")
        if not os.path.exists(self.sounds_dir):
            os.makedirs(self.sounds_dir, exist_ok=True)

    @commands.command(name="upload_sound")
    async def upload_sound(self, ctx, name: str = None):
        """Загрузить звук в саунд-пад. Прикрепите MP3/WAV."""
        if not ctx.message.attachments:
            return await ctx.send("❌ Прикрепите файл MP3 или WAV.")
        
        att = ctx.message.attachments[0]
        if not (att.filename.endswith(".mp3") or att.filename.endswith(".wav")):
             return await ctx.send("❌ Только MP3 или WAV.")
        
        # Check constraints
        MAX_SIZE = 2 * 1024 * 1024 # 2MB
        if att.size > MAX_SIZE:
             return await ctx.send("❌ Файл слишком большой (>2MB).")

        if not name:
            name = att.filename.rsplit('.', 1)[0]
        name = "".join(x for x in name if x.isalnum() or x in " _-").strip()[:32]

        # Check cost
        config = await self.bot.db.get_config(ctx.guild.id)
        price = config.get("soundpad_price", 500)
        
        bypass = dev_manager.is_god_mode(ctx.author.id)
        
        # BUFF CHECK: Sound Pass
        if hasattr(self.bot, 'buff_manager'):
            has_pass = await self.bot.buff_manager.has_buff(ctx.guild.id, ctx.author.id, "sound_free")
            if has_pass:
                bypass = True

        if not bypass:
            bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
            if bal < price:
                return await ctx.send(f"❌ Нужно {price} монет. У вас {bal}.")

        # Download & Validate
        temp_path = os.path.join(self.sounds_dir, f"temp_{ctx.author.id}_{int(time.time())}.{att.filename.split('.')[-1]}")
        try:
            await att.save(temp_path)
            
            # Pydub Check
            seg = AudioSegment.from_file(temp_path)
            duration = len(seg) / 1000.0
            
            if duration > 10.0:
                os.remove(temp_path)
                return await ctx.send("❌ Длительность не более 10 сек.")
            
            if seg.dBFS == -float("inf"):
                os.remove(temp_path)
                return await ctx.send("❌ Файл пустой (тишина).")
            
            # Normalize if too quiet, clamp if too loud? 
            # Simple check: if RMS is extremely loud (unlikely with pydub unless raw data), reject?
            # Let's just limit max duration for now.
            
            # Save final
            final_filename = f"{ctx.guild.id}_{int(time.time())}_{name}.mp3"
            final_path = os.path.join(self.sounds_dir, final_filename)
            seg.export(final_path, format="mp3")
            
            os.remove(temp_path)
            
            # DB & Payment
            if not bypass:
                await self.bot.db.update_balance(ctx.guild.id, ctx.author.id, -price)
                
            await self.bot.db.add_soundpad_sound(ctx.guild.id, ctx.author.id, name, final_path, duration)
            await ctx.send(f"✅ Звук **{name}** добавлен! Списано {price if not bypass else 0} монет.")
            
        except Exception as e:
            if os.path.exists(temp_path): os.remove(temp_path)
            await ctx.send(f"Ошибка обработки: {e}")

    @commands.command(name="pad")
    async def pad_menu(self, ctx):
        """Меню саунд-пада."""
        sounds = await self.bot.db.get_soundpad_sounds(ctx.guild.id)
        if not sounds:
            return await ctx.send("В саунд-паде пусто.")
        
        view = SoundpadSelectView(self.bot, sounds)
        await ctx.send("🎵 **Саунд-Пад** (выберите звук):", view=view)

class SoundpadSelect(discord.ui.Select):
    def __init__(self, bot, sounds):
        self.bot = bot
        options = []
        for s in sounds[:25]: # Discord limit
            options.append(discord.SelectOption(label=s['name'], value=str(s['sound_id'])))
        super().__init__(placeholder="Выберите звук...", options=options)

    async def callback(self, interaction: discord.Interaction):
        # Play sound logic
        # We need to find the VoiceLogger for this guild
        logger = self.bot.loggers.get(interaction.guild_id)
        if not logger or not logger.is_recording:
             return await interaction.response.send_message("❌ Бот не в канале.", ephemeral=True)
             
        # Get path
        # Optimization: We could store path in value but it might be long.
        # Reread from DB or pass dict.
        # Actually we passed 'sounds' list to View, let's look it up.
        sid = int(self.values[0])
        path = None
        name = ""
        
        # We need to access parent view's data or query DB. 
        # Simpler: query DB by ID.
        # But for speed, let's try to pass data.
        # Limitation: Select class is decoupled.
        
        # Let's just query one row, it is fast.
        # But wait, app_db doesn't have get_sound_by_id yet. 
        # I'll rely on the fact that I have the list in the View if I restructure.
        # For now, quick DB fetch via custom query or just iterate the list passed to constructor if I save it.
        pass 
        # Fix: Save sounds in self
        found = next((x for x in self.view.sounds if str(x['sound_id']) == str(sid)), None)
        if found:
            success = await logger.play_sound(found['file_path'])
            if success:
                await interaction.response.send_message(f"▶️ Играет: {found['name']}", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка воспроизведения (занят или не в войсе).", ephemeral=True)
        else:
            await interaction.response.send_message("Звук не найден.", ephemeral=True)

class SoundpadSelectView(discord.ui.View):
    def __init__(self, bot, sounds):
        super().__init__()
        self.sounds = sounds
        self.add_item(SoundpadSelect(bot, sounds))

async def setup(bot):
    await bot.add_cog(SoundpadCog(bot))
