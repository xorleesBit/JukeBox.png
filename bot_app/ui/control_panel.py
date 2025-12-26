import discord
import json
from .ui import (
    LoggerSettingsView, PrankSettingsView, AudioSettingsView, 
    UserManagementView, PlaybackView, AIView, FavoritesView
)

# --- Helpers ---
def _b(v: bool) -> str: return "🟢 ВКЛ" if v else "🔴 ВЫКЛ"

def build_home_embed(guild: discord.Guild, logger, settings, db, stats=None) -> discord.Embed:
    e = discord.Embed(title=f"🎛️ Панель Управления: {guild.name}", color=0x2b2d31)
    
    # 1. Status Section (Big & Clear)
    status_icon = "🔴"
    status_text = "Остановлен"
    voice_name = "—"
    
    if logger:
        if logger.is_recording:
            status_icon = "🟢"
            status_text = "Запись идет"
            if logger.is_paused:
                status_icon = "🟡" 
                status_text = "Пауза (Auto)"
        
        if logger.vc and logger.vc.channel:
            voice_name = logger.vc.channel.name
            if len(voice_name) > 30: voice_name = voice_name[:27] + "..."
    
    e.add_field(
        name="СОСТОЯНИЕ", 
        value=f"```ansi\n\u001b[1;37m{status_icon} {status_text}\u001b[0m\n```", 
        inline=True
    )
    
    e.add_field(
        name="КАНАЛ", 
        value=f"```\n🔊 {voice_name}\n```", 
        inline=True
    )
    
    # 2. Tech Stats
    queue = logger.processor.queue_size() if (logger and hasattr(logger, 'processor')) else 0
    auto_pause_mins = settings.get_int("auto_pause_minutes") or 10
    ap_str = f"{auto_pause_mins}m" if auto_pause_mins > 0 else "OFF"
    
    tech_info = f"⏳ Очередь: **{queue}** | ⏱️ Авто-пауза: **{ap_str}**"
    e.add_field(name="ИНФО", value=tech_info, inline=False)

    # 3. Settings Overview (Compact)
    prank_rec = "✅" if settings.get_bool("prank_capture_enabled") else "❌"
    prank_play = "✅" if settings.get_bool("prank_play_enabled") else "❌"
    auto_tune = "✅" if settings.get_bool("prank_auto_tune_enabled") else "❌"
    
    e.add_field(name="Пранк Режим", value=f"`Rec:{prank_rec}` `Play:{prank_play}` `Tune:{auto_tune}`", inline=True)
    
    # 4. DB Stats
    total = stats.get('total', 0) if stats else 0
    users = stats.get('users', 0) if stats else 0
    e.add_field(name="База Знаний", value=f"💾 Фраз: `{total}`\n👥 Героев: `{users}`", inline=True)

    e.set_footer(text="Loger Bot v3.0 | Используйте меню снизу для настройки")
    return e

# --- Select Menus ---

class AutoPauseSelect(discord.ui.Select):
    def __init__(self, bot, guild_id):
        self.bot_app = bot
        self.guild_id = guild_id
        options = [
            discord.SelectOption(label="Выкл", emoji="🚫", value="0"),
            discord.SelectOption(label="2 мин", emoji="⚡", value="2"),
            discord.SelectOption(label="5 мин", emoji="⏱️", value="5"),
            discord.SelectOption(label="10 мин", emoji="🕰️", value="10"),
            discord.SelectOption(label="30 мин", emoji="💤", value="30"),
        ]
        super().__init__(placeholder="⏱️ Авто-пауза...", min_values=1, max_values=1, options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        try:
            val = int(self.values[0])
            await self.bot_app.db.set_auto_pause_delay(self.guild_id, val)
            # Update settings cache
            settings = await self.bot_app.get_settings(self.guild_id)
            settings.set_int("auto_pause_minutes", val)
            
            # Update active logger
            logger = self.bot_app.loggers.get(self.guild_id)
            if logger:
                logger.auto_pause_minutes = val
            
            if not interaction.response.is_done():
                await interaction.response.defer()
            # Parent view refresh logic handles UI update
        except Exception:
            pass

class MainMenuSelect(discord.ui.Select):
    def __init__(self, bot, guild_id):
        self.bot_app = bot
        self.guild_id = guild_id
        options = [
            discord.SelectOption(label="Настройки Логгера", emoji="⚙️", value="logger_cfg", description="Таймеры, авто-выгрузка"),
            discord.SelectOption(label="Настройки Пранка", emoji="🤡", value="prank_cfg", description="Лимиты, шансы, эффекты"),
            discord.SelectOption(label="Настройки Звука", emoji="🔊", value="audio_cfg", description="Фильтры, шумоподавление"),
            discord.SelectOption(label="Управление Юзерами", emoji="👥", value="users_cfg", description="Блокировка/Разблокировка"),
            discord.SelectOption(label="AI Профили", emoji="🧠", value="ai_menu", description="Генерация профилей"),
            discord.SelectOption(label="Магазин", emoji="🛒", value="shop_menu", description="Покупка предметов"),
            discord.SelectOption(label="Инвентарь", emoji="🎒", value="inventory_menu", description="Ваши предметы"),
        ]
        super().__init__(placeholder="📂 Открыть меню...", min_values=1, max_values=1, options=options, row=4)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        db = self.bot_app.db
        settings = await self.bot_app.get_settings(self.guild_id)
        logger = self.bot_app.loggers.get(self.guild_id)

        if val == "logger_cfg":
            if not logger: return await interaction.response.send_message("Логгер не запущен.", ephemeral=True)
            await interaction.response.send_message("⚙️ **Настройки Логгера**", view=LoggerSettingsView(logger), ephemeral=True)
        
        elif val == "prank_cfg":
            # Pass self as parent, because self has bot_app attribute which PrankSettingsView expects
            await interaction.response.send_message("🤡 **Настройки Пранков**", view=PrankSettingsView(settings, self), ephemeral=True)
            
        elif val == "audio_cfg":
            await interaction.response.send_message("🔊 **Настройки Звука**", view=AudioSettingsView(settings), ephemeral=True)
            
        elif val == "users_cfg":
            await interaction.response.send_message("👥 **Управление**", view=UserManagementView(db, self.guild_id), ephemeral=True)
            
        elif val == "ai_menu":
             profiles = await db.get_all_profiles(self.guild_id)
             await interaction.response.send_message("🧠 **AI Панель**", view=AIView(db, self.guild_id, interaction.guild.name, profiles), ephemeral=True)
        
        elif val == "shop_menu":
            from bot_app.ui.shop_menu import ShopView
            await interaction.response.send_message("🛒 **Магазин**", view=ShopView(db, self.guild_id), ephemeral=True)
        
        elif val == "inventory_menu":
            from bot_app.ui.inventory_menu import InventoryView
            view = InventoryView(db, self.guild_id, interaction.user.id)
            await view.start(interaction)

# --- Main View ---

class ControlPanelView(discord.ui.View):
    def __init__(self, app, guild_id: int):
        super().__init__(timeout=None)
        self.app = app
        self.guild_id = int(guild_id)
        self.add_item(MainMenuSelect(app, guild_id))
        # AutoPauseSelect removed - only in LoggerSettingsView

        # Fix IDs for persistence
        for item in self.children:
            if hasattr(item, "custom_id") and item.custom_id:
                if not item.custom_id.endswith(f":{guild_id}"):
                    item.custom_id = f"{item.custom_id}:{guild_id}"

    async def refresh(self, interaction: discord.Interaction):
        db = self.app.db
        logger = self.app.loggers.get(self.guild_id)
        settings = await self.app.get_settings(self.guild_id)
        stats = await db.count_phrases(self.guild_id)
        embed = build_home_embed(interaction.guild, logger, settings, db, stats)
        
        if interaction.response.is_done():
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                # If editing original response fails (e.g. not found), we can't do much here
                pass
        else:
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass

    # --- Actions Row (0) ---
    @discord.ui.button(label="Старт", style=discord.ButtonStyle.success, row=0, custom_id="cp:start")
    async def btn_start(self, interaction: discord.Interaction, _):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception:
            pass
        await self.app.ensure_logger_started(interaction)
        await self.refresh(interaction)

    @discord.ui.button(label="Стоп", style=discord.ButtonStyle.danger, row=0, custom_id="cp:stop")
    async def btn_stop(self, interaction: discord.Interaction, _):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception:
            pass
        await self.app.ensure_logger_stopped(self.guild_id)
        await self.refresh(interaction)

    @discord.ui.button(label="Пауза", style=discord.ButtonStyle.secondary, row=0, custom_id="cp:pause")
    async def btn_pause(self, interaction: discord.Interaction, _):
        logger = self.app.loggers.get(self.guild_id)
        if logger:
            logger.is_paused = not logger.is_paused
            await logger.update_dashboard()
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception:
            pass
        await self.refresh(interaction)
        
    @discord.ui.button(label="Обновить", style=discord.ButtonStyle.secondary, emoji="🔄", row=0, custom_id="cp:refresh")
    async def btn_refresh(self, interaction: discord.Interaction, _):
        await self.refresh(interaction)

    # --- Feature Row (2) ---
    # --- Feature Row (2) ---
    @discord.ui.button(label="Выгрузить", style=discord.ButtonStyle.success, emoji="📤", row=2, custom_id="cp:upload")
    async def btn_upload(self, interaction: discord.Interaction, _):
        logger = self.app.loggers.get(self.guild_id)
        if logger:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception: pass
            
            # Use publish_now but ensure we don't spam files if disabled
            # We assume publish_now adheres to no-audio logic if implemented
            await logger.publish_now(force=True)
            try: await interaction.followup.send("✅ Выгрузка запущена.", ephemeral=True)
            except: pass
        else:
            try: await interaction.response.send_message("Логгер выключен.", ephemeral=True)
            except: pass

    @discord.ui.button(label="Архивы", style=discord.ButtonStyle.primary, emoji="📦", row=2, custom_id="cp:archives")
    async def btn_archives(self, interaction: discord.Interaction, _):
        from bot_app.ui.archive_menu import ArchiveView # Lazy import
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("📦 **Архивы Логов**", view=ArchiveView(self.guild_id), ephemeral=True)
            else:
                 await interaction.followup.send("📦 **Архивы Логов**", view=ArchiveView(self.guild_id), ephemeral=True)
        except Exception:
            pass