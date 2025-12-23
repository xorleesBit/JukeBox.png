import discord
from discord.ext import commands
from bot_app.ui.debug_menu import DebugView

class UserMenuSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👤 Профиль", emoji="📜", value="profile", description="Моя статистика и уровень"),
            discord.SelectOption(label="💰 Экономика", emoji="💳", value="economy", description="Баланс, переводы, магазин"),
            discord.SelectOption(label="🎵 Саунд-Пад", emoji="🎹", value="soundpad", description="Загрузка и воспроизведение звуков"),
            discord.SelectOption(label="🛠️ Утилиты", emoji="🔧", value="utils", description="AFK, Напоминания, Daily"),
            discord.SelectOption(label="ℹ️ Помощь", emoji="❓", value="help", description="Список команд"),
        ]
        super().__init__(placeholder="Выберите категорию...", options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        
        if val == "profile":
            await interaction.response.send_message("Используйте `!balance` для просмотра профиля.", ephemeral=True)
        elif val == "economy":
            msg = (
                "**Команды Экономики:**\n"
                "`!daily` - Ежедневный бонус\n"
                "`!balance` - Проверить баланс\n"
                "`!pay <user> <amount>` - Перевод\n"
                "`!gift <user> <count>` - Подарить фразы\n"
                "`!flip <heads/tails> <amount>` - Монетка\n"
                "`!duel <user> <amount>` - Дуэль"
            )
            await interaction.response.send_message(msg, ephemeral=True)
        elif val == "soundpad":
             msg = (
                 "**Саунд-Пад:**\n"
                 "`!upload_sound` (с файлом) - Загрузить звук\n"
                 "`!pad` - Открыть меню воспроизведения"
             )
             await interaction.response.send_message(msg, ephemeral=True)
        elif val == "utils":
            msg = (
                "**Утилиты:**\n"
                "`!afk <text>` - Уйти в AFK\n"
                "`!remindme 1h <text>` - Напоминание"
            )
            await interaction.response.send_message(msg, ephemeral=True)
        elif val == "help":
             await interaction.response.send_message("Для справки используйте категории этого меню.", ephemeral=True)

class UserMenuView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(UserMenuSelect())

class UserInteraction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="menu")
    async def menu_cmd(self, ctx):
        await ctx.send("📱 **Главное Меню**", view=UserMenuView())

async def setup(bot):
    await bot.add_cog(UserInteraction(bot))