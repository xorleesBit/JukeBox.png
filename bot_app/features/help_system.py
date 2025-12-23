import discord
from discord.ext import commands

class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Основные", description="Общие команды и утилиты", emoji="📜", value="general"),
            discord.SelectOption(label="Экономика", description="Монетки, дуэли, казино", emoji="💰", value="economy"),
            discord.SelectOption(label="AI & Fun", description="Новости, Ачивки, Пранки", emoji="🤖", value="fun"),
            discord.SelectOption(label="Админ", description="Управление ботом", emoji="🛠️", value="admin"),
        ]
        super().__init__(placeholder="Выберите категорию...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        embed = discord.Embed(color=discord.Color.blurple())
        
        if val == "general":
            embed.title = "📜 Основные Команды"
            embed.add_field(name="!clearchat <n>", value="Очистить n сообщений.", inline=False)
            embed.add_field(name="!top", value="Топ активных пользователей.", inline=False)
            embed.add_field(name="!words [user]", value="Топ слов пользователя.", inline=False)
            embed.add_field(name="!phrases [user]", value="Показать сохраненные фразы (пранки).", inline=False)
            
        elif val == "economy":
            embed.title = "💰 Экономика"
            embed.add_field(name="!balance / !bal", value="Ваш кошелек и рейтинг.", inline=False)
            embed.add_field(name="!pay <user> <amount>", value="Перевести деньги.", inline=False)
            embed.add_field(name="!flip <side> <bet>", value="Орел и Решка (heads/tails).", inline=False)
            embed.add_field(name="!duel <user> <bet>", value="Дуэль 1x1 (зависит от рейтинга).", inline=False)
            
        elif val == "fun":
            embed.title = "🤖 AI & Fun"
            embed.add_field(name="!profile [user]", value="Полный профиль (AI описание + Статистика).", inline=False)
            embed.add_field(name="!achs [user]", value="Список достижений пользователя.", inline=False)
            embed.add_field(name="!news", value="Сгенерировать новости сервера (AI).", inline=False)
            embed.add_field(name="!update_achs", value="(Admin) Обновить/раздать ачивки всем.", inline=False)
            embed.add_field(name="Меню 'Пранк'", value="Настройки записи и авто-тюна в панели.", inline=False)
            
        elif val == "admin":
            embed.title = "🛠️ Администрирование"
            embed.add_field(name="!panel", value="Обновить/пересоздать панель управления.", inline=False)
            embed.add_field(name="!setup_panel", value="Принудительно создать канал панели.", inline=False)
            embed.add_field(name="!delete_all_phrases", value="Удалить ВСЕ данные пранков.", inline=False)
            embed.add_field(name="!debug", value="Состояние бота.", inline=False)

        await interaction.response.edit_message(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(HelpSelect())

class CustomHelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="📚 Справка Loger Bot", description="Выберите категорию ниже, чтобы увидеть список команд.", color=discord.Color.gold())
        embed.set_footer(text="Используйте меню для навигации")
        channel = self.get_destination()
        await channel.send(embed=embed, view=HelpView())
