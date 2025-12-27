import discord
from bot_app.core.state import profile_manager

class ProfileModal(discord.ui.Modal, title="Редактирование Профиля"):
    real_name = discord.ui.TextInput(label="Ваше Имя (Реальное)", placeholder="Саня", required=False, max_length=20)
    gender = discord.ui.TextInput(label="Пол (м/ж)", placeholder="м", required=True, max_length=1)
    bio = discord.ui.TextInput(label="О себе / Лор (для ИИ)", placeholder="Люблю рофлить, часто горю в доте...", style=discord.TextStyle.paragraph, required=False, max_length=200)

    def __init__(self, guild_id: int, user_id: int):
        super().__init__()
        self.guild_id = guild_id
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        g_val = self.gender.value.lower().strip()
        gender = "neutral"
        if g_val.startswith("м") or g_val == "m": gender = "male"
        elif g_val.startswith("ж") or g_val == "f": gender = "female"
        
        updates = {
            "real_name": self.real_name.value or None,
            "gender": gender,
            "bio": self.bio.value or ""
        }
        
        await profile_manager.update_profile(self.guild_id, self.user_id, updates)
        await interaction.response.send_message("✅ Профиль обновлен! ИИ запомнил.", ephemeral=True)

class ProfileView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__()
        self.guild_id = guild_id
        self.user_id = user_id

    @discord.ui.button(label="✏️ Изменить данные", style=discord.ButtonStyle.primary)
    async def edit_btn(self, interaction: discord.Interaction, _):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Это не твой профиль!", ephemeral=True)
        await interaction.response.send_modal(ProfileModal(self.guild_id, self.user_id))

    @discord.ui.button(label="Очистить", style=discord.ButtonStyle.danger)
    async def clear_btn(self, interaction: discord.Interaction, _):
        if interaction.user.id != self.user_id:
             return await interaction.response.send_message("Не трогай чужое!", ephemeral=True)
             
        await profile_manager.update_profile(self.guild_id, self.user_id, {
            "real_name": None, "gender": "neutral", "bio": ""
        })
        await interaction.response.send_message("🗑️ Профиль сброшен.", ephemeral=True)
