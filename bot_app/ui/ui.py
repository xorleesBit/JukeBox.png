import discord
import time
import datetime
from bot_app.integrations.ai_client import ask_ai
from bot_app.features.profile_manager import ProfileManager

# --- Constants ---
DURATION_PRESETS = [
    ("1 мин", 60), ("3 мин", 180), ("5 мин", 300),
    ("10 мин", 600), ("15 мин", 900), ("20 мин", 1200), ("30 мин", 1800),
]

TTL_PRESETS = [
    ("Навсегда", 0), ("1 День", 86400), ("3 Дня", 259200),
    ("1 Неделя", 604800), ("2 Недели", 1209600), ("1 Месяц", 2592000),
]

# --- Components ---

class ChunkDurationSelect(discord.ui.Select):
    def __init__(self, logger_obj):
        self.logger = logger_obj
        options = [discord.SelectOption(label=l, value=str(v)) for l, v in DURATION_PRESETS]
        super().__init__(placeholder="Длительность чанка...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not self.logger: return await interaction.response.send_message("Логгер не активен", ephemeral=True)
        sec = int(self.values[0])
        await self.logger.set_chunk_duration(sec)
        await interaction.response.send_message(f"Длительность чанка: {sec}с", ephemeral=True)
        await self.logger.update_dashboard()

class PublishDurationSelect(discord.ui.Select):
    def __init__(self, logger_obj):
        self.logger = logger_obj
        options = [discord.SelectOption(label=l, value=str(v)) for l, v in DURATION_PRESETS]
        super().__init__(placeholder="Интервал отправки...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not self.logger: return await interaction.response.send_message("Логгер не активен", ephemeral=True)
        sec = int(self.values[0])
        await self.logger.set_publish_interval(sec)
        await interaction.response.send_message(f"Интервал отправки: {sec}с", ephemeral=True)
        await self.logger.update_dashboard()

class TTLSelect(discord.ui.Select):
    def __init__(self, settings):
        self.settings = settings
        options = [discord.SelectOption(label=l, value=str(v)) for l, v in TTL_PRESETS]
        super().__init__(placeholder="Срок жизни фраз...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        sec = int(self.values[0])
        self.settings.set_int("prank_phrase_ttl_seconds", sec)
        await interaction.response.send_message(f"Фразы удаляются через: {sec}с", ephemeral=True)

# --- Settings Views ---

class LoggerSettingsView(discord.ui.View):
    def __init__(self, logger_obj):
        super().__init__(timeout=60)
        self.logger = logger_obj
        self.add_item(ChunkDurationSelect(logger_obj))
        self.add_item(PublishDurationSelect(logger_obj))

class PrankSettingsView(discord.ui.View):
    def __init__(self, settings, parent_view):
        super().__init__(timeout=60)
        self.settings = settings
        self.parent_view = parent_view # Kept for signature compatibility
        self.add_item(TTLSelect(settings))

    @discord.ui.button(label="Запись вкл/выкл", style=discord.ButtonStyle.secondary)
    async def toggle_capture(self, interaction: discord.Interaction, _):
        val = not self.settings.get_bool("prank_capture_enabled")
        self.settings.set_bool("prank_capture_enabled", val)
        await interaction.response.send_message(f"Запись пранков: {val}", ephemeral=True)

    @discord.ui.button(label="Воспр. вкл/выкл", style=discord.ButtonStyle.secondary)
    async def toggle_play(self, interaction: discord.Interaction, _):
        val = not self.settings.get_bool("prank_play_enabled")
        self.settings.set_bool("prank_play_enabled", val)
        await interaction.response.send_message(f"Воспроизведение: {val}", ephemeral=True)

    @discord.ui.button(label="Auto-Tune", style=discord.ButtonStyle.primary)
    async def toggle_autotune(self, interaction: discord.Interaction, _):
        val = not self.settings.get_bool("prank_auto_tune_enabled")
        self.settings.set_bool("prank_auto_tune_enabled", val)
        await interaction.response.send_message(f"Auto-Tune режим: {val}", ephemeral=True)

    @discord.ui.button(label="Цена (Money)", style=discord.ButtonStyle.success)
    async def price_btn(self, interaction: discord.Interaction, _):
        class _PriceModal(discord.ui.Modal):
            def __init__(self, s):
                super().__init__(title="Цена за фразу")
                self.s = s
                self.val = discord.ui.TextInput(label="Монеты (0=бесплатно)", default=str(s.get_int("prank_play_cost") or 0), required=True)
                self.add_item(self.val)
            async def on_submit(self, i):
                try:
                    v = int(self.val.value)
                    self.s.set_int("prank_play_cost", v)
                    await i.response.send_message(f"Цена воспроизведения: {v} монет", ephemeral=True)
                except: await i.response.send_message("Ошибка", ephemeral=True)
        await interaction.response.send_modal(_PriceModal(self.settings))

    @discord.ui.button(label="Лимиты", style=discord.ButtonStyle.secondary)
    async def usage_btn(self, interaction: discord.Interaction, _):
        # Combined limit modal
        class _LimitModal(discord.ui.Modal):
            def __init__(self, s):
                super().__init__(title="Лимиты Пранка")
                self.s = s
                self.gl = discord.ui.TextInput(label="Лимит на сервер (0=беск)", default=str(s.get_int("prank_global_usage_limit")), required=True)
                self.ul = discord.ui.TextInput(label="Лимит на юзера (0=беск)", default=str(s.get_int("prank_phrases_per_user")), required=True)
                self.add_item(self.gl)
                self.add_item(self.ul)
            async def on_submit(self, i):
                try:
                    self.s.set_int("prank_global_usage_limit", int(self.gl.value))
                    self.s.set_int("prank_phrases_per_user", int(self.ul.value))
                    await i.response.send_message("Лимиты обновлены.", ephemeral=True)
                except: await i.response.send_message("Ошибка", ephemeral=True)
        await interaction.response.send_modal(_LimitModal(self.settings))

    @discord.ui.button(label="Тайминги", style=discord.ButtonStyle.secondary)
    async def timing_btn(self, interaction: discord.Interaction, _):
        class _TimeModal(discord.ui.Modal):
            def __init__(self, s):
                super().__init__(title="Тайминги")
                self.s = s
                self.rot = discord.ui.TextInput(label="Кулдаун ротации (сек)", default=str(s.get_int("prank_rotation_cooldown_s", 300)), required=True)
                self.inv = discord.ui.TextInput(label="Интервал пранков (мин)", default=str(s.get_int("prank_interval_minutes") or 2), required=True)
                self.spk = discord.ui.TextInput(label="Порог тишины (чел)", default=str(s.get_int("prank_max_concurrent_speakers") or 2), required=True)
                self.add_item(self.rot)
                self.add_item(self.inv)
                self.add_item(self.spk)
            async def on_submit(self, i):
                try:
                    self.s.set_int("prank_rotation_cooldown_s", int(self.rot.value))
                    self.s.set_int("prank_interval_minutes", int(self.inv.value))
                    self.s.set_int("prank_max_concurrent_speakers", int(self.spk.value))
                    await i.response.send_message("Тайминги обновлены.", ephemeral=True)
                except: await i.response.send_message("Ошибка", ephemeral=True)
        await interaction.response.send_modal(_TimeModal(self.settings))

class AudioSettingsView(discord.ui.View):
    def __init__(self, settings):
        super().__init__(timeout=60)
        self.settings = settings

    @discord.ui.button(label="Шумоподавление", style=discord.ButtonStyle.secondary)
    async def toggle_denoise(self, interaction: discord.Interaction, _):
        val = not self.settings.get_bool("audio_denoise_enabled")
        self.settings.set_bool("audio_denoise_enabled", val)
        await interaction.response.send_message(f"Шумоподавление: {val}", ephemeral=True)

    @discord.ui.button(label="Фильтры (HP/LP)", style=discord.ButtonStyle.primary)
    async def set_filter(self, interaction: discord.Interaction, _):
        class _FilterModal(discord.ui.Modal):
            def __init__(self, s):
                super().__init__(title="Аудио Фильтры")
                self.s = s
                self.hp = discord.ui.TextInput(label="High Pass (Hz)", default=str(s.get_int("audio_hp_hz")), required=True)
                self.lp = discord.ui.TextInput(label="Low Pass (Hz)", default=str(s.get_int("audio_lp_hz")), required=True)
                self.add_item(self.hp)
                self.add_item(self.lp)
            async def on_submit(self, i):
                try:
                    self.s.set_int("audio_hp_hz", int(self.hp.value))
                    self.s.set_int("audio_lp_hz", int(self.lp.value))
                    await i.response.send_message("Фильтры обновлены.", ephemeral=True)
                except:
                    await i.response.send_message("Неверные числа.", ephemeral=True)
        await interaction.response.send_modal(_FilterModal(self.settings))

# --- Achievement Editor Views ---

class AchieveModal(discord.ui.Modal):
    def __init__(self, db, guild_id, user_id, existing_data=None, index=None):
        title = "Редактирование" if existing_data else "Новая Ачивка"
        super().__init__(title=title)
        self.db = db; self.guild_id = guild_id; self.user_id = user_id; self.index = index
        self.existing = existing_data

        self.a_title = discord.ui.TextInput(label="Название", required=True, default=(existing_data['title'] if existing_data else "")[:45])
        self.a_desc = discord.ui.TextInput(label="Описание", required=True, style=discord.TextStyle.paragraph, default=(existing_data['desc'] if existing_data else "")[:3900])
        self.a_date = discord.ui.TextInput(label="Дата (YYYY-MM-DD)", required=True, default=(existing_data['date'] if existing_data else str(datetime.date.today()))[:20])
        
        self.add_item(self.a_title)
        self.add_item(self.a_desc)
        self.add_item(self.a_date)

    async def on_submit(self, i: discord.Interaction):
        # Fetch, Modify, Save
        prof = await self.db.get_profile(self.guild_id, self.user_id)
        if not prof: prof = {}
        achs = prof.get('achievements', [])
        if not isinstance(achs, list): achs = []

        new_entry = {"title": self.a_title.value, "desc": self.a_desc.value, "date": self.a_date.value}

        if self.index is not None and 0 <= self.index < len(achs):
            achs[self.index] = new_entry # Edit
            action = "изменена"
        else:
            achs.append(new_entry) # Add
            action = "добавлена"
        
        prof['achievements'] = achs
        await self.db.upsert_profile(self.guild_id, self.user_id, prof)
        await i.response.send_message(f"✅ Ачивка {action}.", ephemeral=True)

class AchieveSelect(discord.ui.Select):
    def __init__(self, achievements):
        options = []
        for idx, a in enumerate(achievements):
            lbl = a.get('title', 'Без названия')[:25]
            desc = a.get('desc', '')[:50]
            options.append(discord.SelectOption(label=f"{idx+1}. {lbl}", description=desc, value=str(idx)))
        if not options:
            options.append(discord.SelectOption(label="Нет ачивок", value="-1"))
        super().__init__(placeholder="Выберите ачивку для правки/удаления...", min_values=1, max_values=1, options=options)

    async def callback(self, i: discord.Interaction):
        if self.values[0] == "-1": return await i.response.send_message("Пусто.", ephemeral=True)
        idx = int(self.values[0])
        self.view.selected_index = idx
        await i.response.send_message(f"Выбрана ачивка #{idx+1}. Используйте кнопки ниже.", ephemeral=True)

class AchievementEditorView(discord.ui.View):
    def __init__(self, db, guild_id, user_id, achievements):
        super().__init__(timeout=120)
        self.db = db; self.guild_id = guild_id; self.user_id = user_id
        self.selected_index = None
        self.achievements = achievements
        self.add_item(AchieveSelect(achievements))

    @discord.ui.button(label="➕ Добавить", style=discord.ButtonStyle.success, row=1)
    async def btn_add(self, i, _):
        await i.response.send_modal(AchieveModal(self.db, self.guild_id, self.user_id))

    @discord.ui.button(label="✏️ Изменить", style=discord.ButtonStyle.primary, row=1)
    async def btn_edit(self, i, _):
        if self.selected_index is None: return await i.response.send_message("Сначала выберите ачивку в списке.", ephemeral=True)
        data = self.achievements[self.selected_index]
        await i.response.send_modal(AchieveModal(self.db, self.guild_id, self.user_id, data, self.selected_index))

    @discord.ui.button(label="🗑️ Удалить", style=discord.ButtonStyle.danger, row=1)
    async def btn_del(self, i, _):
        if self.selected_index is None: return await i.response.send_message("Сначала выберите ачивку в списке.", ephemeral=True)
        
        prof = await self.db.get_profile(self.guild_id, self.user_id)
        if prof and 'achievements' in prof:
            try:
                del prof['achievements'][self.selected_index]
                await self.db.upsert_profile(self.guild_id, self.user_id, prof)
                await i.response.send_message("🗑️ Удалено.", ephemeral=True)
            except: await i.response.send_message("Ошибка удаления.", ephemeral=True)
        else:
            await i.response.send_message("Нет профиля.", ephemeral=True)

class AchieveUserSelect(discord.ui.UserSelect):
    def __init__(self, db, guild_id):
        self.db = db; self.guild_id = guild_id
        super().__init__(placeholder="Чьи ачивки редактировать?")
    
    async def callback(self, i: discord.Interaction):
        user = self.values[0]
        prof = await self.db.get_profile(self.guild_id, user.id)
        achs = prof.get('achievements', []) if prof else []
        
        await i.response.send_message(
            f"🛠️ Редактор ачивок: **{user.display_name}** ({len(achs)} шт)", 
            view=AchievementEditorView(self.db, self.guild_id, user.id, achs),
            ephemeral=True
        )

# --- User Management ---
class UserManagementView(discord.ui.View):
    def __init__(self, db, guild_id):
        super().__init__(timeout=60)
        self.db = db
        self.guild_id = guild_id

    @discord.ui.button(label="🏅 Ред. Ачивок", style=discord.ButtonStyle.primary, row=0)
    async def achs_edit_btn(self, interaction: discord.Interaction, _):
        view = discord.ui.View()
        view.add_item(AchieveUserSelect(self.db, self.guild_id))
        await interaction.response.send_message("Выберите пользователя:", view=view, ephemeral=True)

    @discord.ui.button(label="Заблокировать", style=discord.ButtonStyle.danger, row=1)
    async def block_btn(self, interaction: discord.Interaction, _):
        class _BlockModal(discord.ui.Modal):
            def __init__(self, db, gid):
                super().__init__(title="Блокировка")
                self.db = db; self.gid = gid
                self.uid = discord.ui.TextInput(label="ID для блокировки", required=True)
                self.add_item(self.uid)
            async def on_submit(self, i):
                try:
                    uid = int(self.uid.value)
                    await self.db.set_user_opt_out(self.gid, uid, True)
                    await i.response.send_message(f"Пользователь {uid} заблокирован (не пишем его).", ephemeral=True)
                except:
                    await i.response.send_message("Неверный ID", ephemeral=True)
        await interaction.response.send_modal(_BlockModal(self.db, self.guild_id))

    @discord.ui.button(label="Разблокировать", style=discord.ButtonStyle.success, row=1)
    async def unblock_btn(self, interaction: discord.Interaction, _):
        class _UnblockModal(discord.ui.Modal):
            def __init__(self, db, gid):
                super().__init__(title="Разблокировка")
                self.db = db; self.gid = gid
                self.uid = discord.ui.TextInput(label="ID для разблокировки", required=True)
                self.add_item(self.uid)
            async def on_submit(self, i):
                try:
                    uid = int(self.uid.value)
                    await self.db.set_user_opt_out(self.gid, uid, False)
                    await i.response.send_message(f"Пользователь {uid} разблокирован.", ephemeral=True)
                except:
                    await i.response.send_message("Неверный ID", ephemeral=True)
        await interaction.response.send_modal(_UnblockModal(self.db, self.guild_id))

# --- Playback & Favorites ---

class FXSelect(discord.ui.Select):
    def __init__(self, db, phrase_id, logger):
        self.db = db
        self.phrase_id = phrase_id
        self.logger = logger
        options = [
            discord.SelectOption(label="🎭 Helium", value="helium"),
            discord.SelectOption(label="👺 Demon", value="demon"),
            discord.SelectOption(label="🏰 Reverb", value="reverb"),
        ]
        super().__init__(placeholder="FX Play...", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        # Pay check for manual play with effect (can be same logic)
        # But effect is usually free if play is paid. 
        # Let's assume FX also charges? Or logic is in play_phrase_id?
        # Logic: play_phrase_id is backend. Charges should be UI.
        
        settings = self.logger.settings
        cost = settings.get_int("prank_play_cost") or 0
        user_id = interaction.user.id
        
        if cost > 0:
            bal = await self.db.get_balance(interaction.guild_id, user_id)
            if bal < cost:
                return await interaction.response.send_message(f"Не хватает монет! Нужно {cost}, у вас {bal}.", ephemeral=True)
            await self.db.update_balance(interaction.guild_id, user_id, -cost)
        
        effect = self.values[0]
        if self.logger and self.logger.prank:
            await interaction.response.defer(ephemeral=True)
            await self.logger.prank.play_phrase_id(self.phrase_id, record_play=False, force_effect=effect)
            
            msg = f"Играем FX: {effect}"
            if cost > 0: msg += f" (-{cost} 💰)"
            await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message("Логгер не активен.", ephemeral=True)

class PhraseActionView(discord.ui.View):
    def __init__(self, db, phrase_id, logger):
        super().__init__(timeout=60)
        self.db = db
        self.phrase_id = phrase_id
        self.logger = logger
        self.add_item(FXSelect(db, phrase_id, logger))

    @discord.ui.button(label="⭐ Fav", style=discord.ButtonStyle.success, row=0)
    async def btn_fav(self, interaction: discord.Interaction, _):
        p = await self.db.get_phrase(self.phrase_id)
        if not p: return await interaction.response.send_message("Нет фразы", ephemeral=True)
        new_val = not p['is_favorite']
        await self.db.set_phrase_favorite(self.phrase_id, new_val)
        await interaction.response.send_message(f"Избранное: {new_val}", ephemeral=True)

    @discord.ui.button(label="Play", style=discord.ButtonStyle.secondary, row=0)
    async def btn_play(self, interaction: discord.Interaction, _):
        # PAYMENT LOGIC
        settings = self.logger.settings
        cost = settings.get_int("prank_play_cost") or 0
        user_id = interaction.user.id
        
        if cost > 0:
            bal = await self.db.get_balance(interaction.guild_id, user_id)
            if bal < cost:
                return await interaction.response.send_message(f"Не хватает монет! Нужно {cost}, у вас {bal}.", ephemeral=True)
            await self.db.update_balance(interaction.guild_id, user_id, -cost)

        if self.logger and self.logger.prank:
            await interaction.response.defer(ephemeral=True)
            await self.logger.prank.play_phrase_id(self.phrase_id, record_play=False)
            
            msg = "Играем..."
            if cost > 0: msg += f" (-{cost} 💰)"
            await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message("Логгер не активен", ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary, row=0)
    async def btn_rename(self, interaction: discord.Interaction, _):
        class _RenameModal(discord.ui.Modal):
            def __init__(self, db, pid):
                super().__init__(title="Переименовать")
                self.db = db; self.pid = pid
                self.name = discord.ui.TextInput(label="Имя", required=True)
                self.add_item(self.name)
            async def on_submit(self, i):
                await self.db.set_phrase_name(self.pid, self.name.value)
                await i.response.send_message(f"Имя: {self.name.value}", ephemeral=True)
        await interaction.response.send_modal(_RenameModal(self.db, self.phrase_id))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, row=0)
    async def btn_delete(self, interaction: discord.Interaction, _):
        await self.db.delete_phrase(self.phrase_id)
        await interaction.response.send_message("Удалено.", ephemeral=True)

class PhraseSelect(discord.ui.Select):
    def __init__(self, phrases, db, logger):
        self.db = db
        self.logger = logger
        options = []
        for p in phrases:
            dt = time.strftime("%H:%M", time.localtime(p['created_ts']))
            fav = "⭐" if p['is_favorite'] else ""
            label = f"{fav} #{p['phrase_id']} {p['name'] or 'Без имени'}"
            desc = f"Создано: {dt}"
            options.append(discord.SelectOption(label=label[:100], description=desc, value=str(p['phrase_id'])))
        super().__init__(placeholder="Выберите фразу...", options=options)

    async def callback(self, interaction: discord.Interaction):
        pid = int(self.values[0])
        # Only visible to user who clicked
        await interaction.response.send_message(f"Фраза #{pid}", view=PhraseActionView(self.db, pid, self.logger), ephemeral=True)

class PlaybackView(discord.ui.View):
    def __init__(self, logger):
        super().__init__(timeout=60)
        self.logger = logger

    @discord.ui.button(label="Случайная фраза", style=discord.ButtonStyle.success)
    async def play_rnd(self, interaction: discord.Interaction, _):
        if not self.logger or not self.logger.prank: return await interaction.response.send_message("Логгер выключен", ephemeral=True)
        
        # Payment for random? Probably yes
        settings = self.logger.settings
        cost = settings.get_int("prank_play_cost") or 0
        user_id = interaction.user.id
        
        if cost > 0:
            bal = await self.logger.db.get_balance(interaction.guild_id, user_id) # access db via logger
            if bal < cost: return await interaction.response.send_message(f"Не хватает монет! Нужно {cost}.", ephemeral=True)
            await self.logger.db.update_balance(interaction.guild_id, user_id, -cost)

        await interaction.response.defer(ephemeral=True)
        await self.logger.prank.play_random()
        
        msg = "🎲 Играем..."
        if cost > 0: msg += f" (-{cost} 💰)"
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="По ID", style=discord.ButtonStyle.secondary)
    async def play_id(self, interaction: discord.Interaction, _):
        class _PlayModal(discord.ui.Modal):
            def __init__(self, logger):
                super().__init__(title="Играть по ID")
                self.logger = logger
                self.pid = discord.ui.TextInput(label="ID", required=True)
                self.add_item(self.pid)
            async def on_submit(self, i):
                try:
                    # Payment here too? Yes.
                    settings = self.logger.settings
                    cost = settings.get_int("prank_play_cost") or 0
                    user_id = i.user.id
                    
                    if cost > 0:
                        bal = await self.logger.db.get_balance(i.guild_id, user_id)
                        if bal < cost: return await i.response.send_message(f"Не хватает монет! Нужно {cost}.", ephemeral=True)
                        await self.logger.db.update_balance(i.guild_id, user_id, -cost)

                    await self.logger.prank.play_phrase_id(int(self.pid.value), record_play=False)
                    
                    msg = "Ок"
                    if cost > 0: msg += f" (-{cost} 💰)"
                    await i.response.send_message(msg, ephemeral=True)
                except: await i.response.send_message("Ошибка", ephemeral=True)
        await interaction.response.send_modal(_PlayModal(self.logger))

class UserSelect(discord.ui.UserSelect):
    def __init__(self, db, logger, guild_id):
        self.db = db; self.logger = logger; self.guild_id = guild_id
        super().__init__(placeholder="Выберите пользователя...")

    async def callback(self, interaction: discord.Interaction):
        # Filter logic here? Or just show all.
        # User requested: "is not shown only for user but hangs for everyone".
        # This interaction response IS ephemeral=True below.
        # But the !phrases command output is what they meant.
        user = self.values[0]
        phrases = await self.db.get_all_user_phrases(self.guild_id, user.id, limit=25)
        if not phrases: return await interaction.response.send_message("Нет фраз.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(PhraseSelect(phrases, self.db, self.logger))
        await interaction.response.send_message(f"Фразы {user.display_name}:", view=view, ephemeral=True)

class FavoritesView(discord.ui.View):
    def __init__(self, db, logger, guild_id):
        super().__init__(timeout=60)
        self.add_item(UserSelect(db, logger, guild_id))

# --- AI ---

class AIModal(discord.ui.Modal, title="AI Chat"):
    prompt = discord.ui.TextInput(label="Вопрос", style=discord.TextStyle.paragraph, required=True)
    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        ans = await ask_ai(self.prompt.value)
        if len(ans) > 1900:
             chunks = [ans[j:j+1900] for j in range(0, len(ans), 1900)]
             for c in chunks: await i.followup.send(c, ephemeral=True)
        else: await i.followup.send(ans, ephemeral=True)

class ProfileUserSelect(discord.ui.UserSelect):
    def __init__(self, db, guild_id):
        self.db = db; self.guild_id = guild_id
        super().__init__(placeholder="Чей профиль?")
    async def callback(self, i):
        u = self.values[0]
        p = await self.db.get_profile(self.guild_id, u.id)
        if not p: return await i.response.send_message("Профиль не готов.", ephemeral=True)
        e = discord.Embed(title=f"Профиль: {u.display_name}", color=discord.Color.teal())
        for k, v in p.items(): 
            if v and isinstance(v, list): val = ", ".join(v)
            elif isinstance(v, dict): val = str(v)
            else: val = str(v)
            e.add_field(name=k.capitalize(), value=val[:1024], inline=False)
        await i.response.send_message(embed=e, ephemeral=True)

class AIView(discord.ui.View):
    def __init__(self, db, guild_id, guild_name, profiles):
        super().__init__(timeout=120)
        self.db = db; self.guild_id = guild_id; self.guild_name = guild_name
        self.add_item(ProfileUserSelect(db, guild_id))
    
    @discord.ui.button(label="Анализ (Обновить)", style=discord.ButtonStyle.primary, row=1)
    async def btn_analyze(self, i, _):
        await i.response.send_message("Запущен анализ...", ephemeral=True)
        rep = await ProfileManager(self.db, self.guild_id).run_analysis(self.guild_name)
        await i.followup.send(rep, ephemeral=True)

    @discord.ui.button(label="Чат", style=discord.ButtonStyle.secondary, row=1)
    async def btn_chat(self, i, _):
        await i.response.send_modal(AIModal())

# --- Control View (Bottom of Panel) ---
class ControlView(discord.ui.View):
    def __init__(self, logger_obj):
        super().__init__(timeout=None)
        self.logger = logger_obj

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if not self.logger or not self.logger.bot: return False
        perms = interaction.user.guild_permissions if interaction.guild else None
        return bool(perms and (perms.manage_guild or perms.administrator or perms.manage_messages))

    @discord.ui.button(label="Пауза", style=discord.ButtonStyle.secondary)
    async def pause_btn(self, interaction: discord.Interaction, _):
        if not await self._guard(interaction): return await interaction.response.send_message("Нет прав.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        self.logger.is_paused = True
        await self.logger.update_dashboard()

    @discord.ui.button(label="Продолжить", style=discord.ButtonStyle.success)
    async def resume_btn(self, interaction: discord.Interaction, _):
        if not await self._guard(interaction): return await interaction.response.send_message("Нет прав.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        self.logger.is_paused = False
        await self.logger.update_dashboard()

    @discord.ui.button(label="Стоп", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, _):
        if not await self._guard(interaction): return await interaction.response.send_message("Нет прав.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.logger.stop()
        await self.logger.update_dashboard()

    @discord.ui.button(label="Загрузить сейчас", style=discord.ButtonStyle.secondary)
    async def upload_btn(self, interaction: discord.Interaction, _):
        if not await self._guard(interaction): return await interaction.response.send_message("Нет прав.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.logger.publish_now(force=True)
        await self.logger.update_dashboard()