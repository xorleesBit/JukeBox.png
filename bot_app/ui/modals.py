import discord
from discord.ui import Modal, TextInput

class PayModal(Modal, title="Перевод монет"):
    recipient_name = TextInput(label="Кому (Имя или ID)", placeholder="User123")
    amount = TextInput(label="Сумма", placeholder="100", min_length=1)

    def __init__(self, db, guild_id):
        super().__init__()
        self.db = db
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value)
            if amt <= 0: raise ValueError
        except:
            return await interaction.response.send_message("❌ Сумма должна быть числом > 0.", ephemeral=True)

        target_id = await self.db.get_user_id_by_name(self.guild_id, self.recipient_name.value)
        if not target_id:
            # Try parsing ID
            try: target_id = int(self.recipient_name.value)
            except: return await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)

        if target_id == interaction.user.id:
            return await interaction.response.send_message("❌ Нельзя переводить себе.", ephemeral=True)

        bal = await self.db.get_balance(self.guild_id, interaction.user.id)
        if bal < amt:
            return await interaction.response.send_message(f"❌ Недостаточно средств ({bal}).", ephemeral=True)

        await self.db.update_balance(self.guild_id, interaction.user.id, -amt)
        await self.db.update_balance(self.guild_id, target_id, amt)
        await interaction.response.send_message(f"✅ Переведено **{amt}** монет пользователю <@{target_id}>.", ephemeral=True)

class GiftModal(Modal, title="Подарить фразы"):
    recipient_name = TextInput(label="Кому (Имя или ID)", placeholder="User123")
    count = TextInput(label="Количество", placeholder="1", min_length=1)

    def __init__(self, db, guild_id):
        super().__init__()
        self.db = db
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cnt = int(self.count.value)
            if cnt <= 0: raise ValueError
        except:
            return await interaction.response.send_message("❌ Количество должно быть числом.", ephemeral=True)

        target_id = await self.db.get_user_id_by_name(self.guild_id, self.recipient_name.value)
        if not target_id:
            try: target_id = int(self.recipient_name.value)
            except: return await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)

        cost = cnt * 50 # Hardcoded price for now
        bal = await self.db.get_balance(self.guild_id, interaction.user.id)
        
        if bal < cost:
            return await interaction.response.send_message(f"❌ Нужно {cost} монет. У вас {bal}.", ephemeral=True)

        await self.db.update_balance(self.guild_id, interaction.user.id, -cost)
        await self.db.add_free_plays(self.guild_id, target_id, cnt)
        await interaction.response.send_message(f"🎁 Подарено **{cnt}** фраз пользователю <@{target_id}>!", ephemeral=True)

class RemindModal(Modal, title="Создать напоминание"):
    time_str = TextInput(label="Через сколько? (10m, 1h)", placeholder="1h")
    text = TextInput(label="О чем напомнить?", style=discord.TextStyle.paragraph)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        # We invoke the logic from UtilitiesCog manually or replicate it
        # Replication is safer for decoupled UI
        import time, re
        seconds = 0
        match = re.match(r"(\d+)([mhd])", self.time_str.value.lower())
        if match:
            val = int(match.group(1))
            unit = match.group(2)
            if unit == 'm': seconds = val * 60
            elif unit == 'h': seconds = val * 3600
            elif unit == 'd': seconds = val * 86400
        else:
            return await interaction.response.send_message("❌ Неверный формат времени.", ephemeral=True)

        due_ts = time.time() + seconds
        await self.bot.db.add_reminder(interaction.user.id, interaction.channel.id, due_ts, self.text.value)
        await interaction.response.send_message(f"⏰ Напоминание установлено!", ephemeral=True)

class AFKModal(Modal, title="Уйти в AFK"):
    message = TextInput(label="Сообщение", placeholder="Отошел в магазин...", required=False)

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        msg = self.message.value or "AFK"
        await self.db.set_afk(interaction.user.id, interaction.guild.id, msg)
        try:
            dn = interaction.user.display_name
            if not dn.startswith("[AFK]"):
                await interaction.user.edit(nick=f"[AFK] {dn}"[:32])
        except: pass
        await interaction.response.send_message(f"💤 Статус AFK установлен: {msg}", ephemeral=True)
