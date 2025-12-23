import discord
import time
from bot_app.ui.modals import PayModal, GiftModal, RemindModal, AFKModal

class UserMenuView(discord.ui.View):
    def __init__(self, bot, user, interaction_to_edit=None):
        super().__init__(timeout=300)
        self.bot = bot
        self.user = user
        self.db = bot.db
        self.current_screen = "main"
        
        # Initial Render
        self._setup_main_menu()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("Это меню открыто не для вас.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        # Disable all items
        for child in self.children:
            child.disabled = True
        # Note: Can't edit ephemeral message after timeout easily if we don't have handle, 
        # but View stops responding anyway.
        pass

    # --- Screens ---

    def _setup_main_menu(self):
        self.clear_items()
        
        # Select Menu
        select = discord.ui.Select(placeholder="Выберите категорию...", options=[
            discord.SelectOption(label="Профиль", emoji="📜", value="profile", description="Статистика, уровень, рейтинг"),
            discord.SelectOption(label="Экономика", emoji="💳", value="economy", description="Баланс, ежедневные бонусы, переводы"),
            discord.SelectOption(label="Саунд-Пад", emoji="🎹", value="soundpad", description="Ваши звуки и плеер"),
            discord.SelectOption(label="Утилиты", emoji="🛠️", value="utils", description="AFK, Напоминания"),
        ])
        
        async def callback(interaction: discord.Interaction):
            val = select.values[0]
            if val == "profile": await self._show_profile(interaction)
            elif val == "economy": await self._show_economy(interaction)
            elif val == "soundpad": await self._show_soundpad(interaction)
            elif val == "utils": await self._show_utils(interaction)
        
        select.callback = callback
        self.add_item(select)

    async def _get_main_embed(self, guild_id):
        u_data = await self.db.get_user(guild_id, self.user.id)
        bal = u_data['balance'] if u_data else 0
        lvl = u_data['level'] if u_data else 1
        
        e = discord.Embed(title=f"📱 Личный кабинет: {self.user.display_name}", color=discord.Color.blue())
        e.description = "Выберите категорию в меню ниже для управления."
        e.add_field(name="💰 Баланс", value=f"{bal}", inline=True)
        e.add_field(name="📊 Уровень", value=f"{lvl}", inline=True)
        e.set_thumbnail(url=self.user.display_avatar.url)
        return e

    # --- Profile ---
    async def _show_profile(self, interaction: discord.Interaction):
        self.clear_items()
        self._add_back_button()
        
        u_data = await self.db.get_user(interaction.guild_id, self.user.id)
        if not u_data: u_data = {}
        
        stats = await self.db.get_user_phrase_stats(interaction.guild_id, self.user.id)
        phrases_cnt = stats['cnt'] if stats else 0
        
        e = discord.Embed(title="📜 Профиль", color=discord.Color.gold())
        e.add_field(name="Уровень", value=str(u_data.get('level', 1)), inline=True)
        e.add_field(name="Опыт (XP)", value=str(u_data.get('xp', 0)), inline=True)
        e.add_field(name="Рейтинг", value=str(u_data.get('rating', 1000)), inline=True)
        e.add_field(name="Слов (Текст)", value=str(u_data.get('words_text_total', 0)), inline=True)
        e.add_field(name="Слов (Голос)", value=str(u_data.get('words_audio_total', 0)), inline=True)
        e.add_field(name="Фраз в базе", value=str(phrases_cnt), inline=True)
        
        await interaction.response.edit_message(embed=e, view=self)

    # --- Economy ---
    async def _show_economy(self, interaction: discord.Interaction):
        self.clear_items()
        
        # Actions
        btn_daily = discord.ui.Button(label="Получить Daily", style=discord.ButtonStyle.success, emoji="🎁")
        async def daily_cb(itx: discord.Interaction):
            # Logic duplication from Cog, but simpler to invoke directly or recreate
            # Let's recreate logic for speed
            user_row = await self.db.get_user(itx.guild_id, self.user.id)
            last = user_row.get("daily_last_claim_ts", 0) if user_row else 0
            if time.time() - last < 86400:
                await itx.response.send_message(f"⏳ Рано! Жди <t:{int(last+86400)}:R>", ephemeral=True)
            else:
                amt = 100
                await self.db.claim_daily(itx.guild_id, self.user.id, amt)
                await self._show_economy(itx) # Refresh
                await itx.followup.send(f"✅ Получено {amt} монет!", ephemeral=True)
        btn_daily.callback = daily_cb
        self.add_item(btn_daily)

        btn_pay = discord.ui.Button(label="Перевод", style=discord.ButtonStyle.primary, emoji="💸")
        async def pay_cb(itx: discord.Interaction):
            await itx.response.send_modal(PayModal(self.db, itx.guild_id))
        btn_pay.callback = pay_cb
        self.add_item(btn_pay)

        btn_gift = discord.ui.Button(label="Подарить Фразы", style=discord.ButtonStyle.secondary, emoji="🎁")
        async def gift_cb(itx: discord.Interaction):
            await itx.response.send_modal(GiftModal(self.db, itx.guild_id))
        btn_gift.callback = gift_cb
        self.add_item(btn_gift)

        self._add_back_button()

        u_data = await self.db.get_user(interaction.guild_id, self.user.id)
        bal = u_data.get('balance', 0)
        free = u_data.get('free_phrase_plays', 0)
        
        e = discord.Embed(title="💳 Экономика", color=discord.Color.green())
        e.add_field(name="Текущий Баланс", value=f"**{bal}** 💰", inline=False)
        e.add_field(name="Бесплатные Фразы", value=f"**{free}** шт.", inline=False)
        e.description = "Нажмите кнопки ниже для действий."
        
        await interaction.response.edit_message(embed=e, view=self)

    # --- Soundpad ---
    async def _show_soundpad(self, interaction: discord.Interaction):
        self.clear_items()
        
        # Just info + Upload instruction?
        # Or Open Pad button
        btn_pad = discord.ui.Button(label="Открыть Плеер", style=discord.ButtonStyle.primary, emoji="▶️")
        async def pad_cb(itx: discord.Interaction):
             # Trigger the Soundpad Select View (from SoundpadCog logic)
             # We import it locally to avoid circular dependency issues at top level if any
             from bot_app.cogs.soundpad import SoundpadSelectView
             sounds = await self.db.get_soundpad_sounds(itx.guild_id)
             if not sounds:
                 return await itx.response.send_message("📂 Папка пуста.", ephemeral=True)
             await itx.response.send_message("🎵 Плеер:", view=SoundpadSelectView(self.bot, sounds), ephemeral=True)
        btn_pad.callback = pad_cb
        self.add_item(btn_pad)
        
        self._add_back_button()
        
        e = discord.Embed(title="🎹 Саунд-Пад", color=discord.Color.purple())
        e.description = (
            "Для загрузки звука используйте команду:\n"
            "`!upload_sound [имя]` (прикрепите файл)\n\n"
            "Нажмите кнопку ниже, чтобы открыть меню воспроизведения."
        )
        await interaction.response.edit_message(embed=e, view=self)

    # --- Utils ---
    async def _show_utils(self, interaction: discord.Interaction):
        self.clear_items()
        
        btn_afk = discord.ui.Button(label="AFK Статус", style=discord.ButtonStyle.secondary, emoji="💤")
        async def afk_cb(itx: discord.Interaction):
            await itx.response.send_modal(AFKModal(self.db))
        btn_afk.callback = afk_cb
        self.add_item(btn_afk)

        btn_remind = discord.ui.Button(label="Напоминание", style=discord.ButtonStyle.secondary, emoji="⏰")
        async def rem_cb(itx: discord.Interaction):
            await itx.response.send_modal(RemindModal(self.bot))
        btn_remind.callback = rem_cb
        self.add_item(btn_remind)

        self._add_back_button()
        
        e = discord.Embed(title="🛠️ Утилиты", color=discord.Color.dark_grey())
        e.description = "Быстрый доступ к инструментам."
        await interaction.response.edit_message(embed=e, view=self)

    # --- Helpers ---
    def _add_back_button(self):
        btn = discord.ui.Button(label="Назад", style=discord.ButtonStyle.danger, row=4)
        async def back_cb(itx: discord.Interaction):
            self._setup_main_menu()
            embed = await self._get_main_embed(itx.guild_id)
            await itx.response.edit_message(embed=embed, view=self)
        btn.callback = back_cb
        self.add_item(btn)
