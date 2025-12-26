import discord
from discord.ext import commands

class CustomHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__(
            command_attrs={
                "name": "help",
                "aliases": ["помощь", "h"],
                "help": "Показывает это сообщение",
                "cooldown": commands.CooldownMapping.from_cooldown(1, 3.0, commands.BucketType.user)
            }
        )

    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="📚 Помощь по командам", color=discord.Color.blurple())
        
        for cog, cmds in mapping.items():
            # Skip empty Cogs or hidden Cogs
            if not cmds: continue
            
            # Filter commands
            filtered_cmds = await self.filter_commands(cmds, sort=True)
            if not filtered_cmds: continue
            
            cog_name = cog.qualified_name if cog else "Без категории"
            
            # FILTER: Hide specific cogs
            if cog_name.lower() in ["debugcog", "taskscog", "admincommands", "utilitiescog", "eventscog"]:
                # Hide these cogs entirely from user view
                continue
                
            cmd_list = []
            for cmd in filtered_cmds:
                # Filter individual commands
                if cmd.name in ["debug", "metrics", "test", "sync", "reload"]:
                    continue
                cmd_list.append(f"`{self.context.prefix}{cmd.name}`")
            
            if cmd_list:
                embed.add_field(name=cog_name, value=", ".join(cmd_list), inline=False)
        
        embed.set_footer(text=f"Используйте {self.context.prefix}help <команда> для деталей")
        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        # Hide help for restricted commands
        if command.name in ["debug", "metrics", "test", "sync", "reload"] or (command.cog and command.cog.qualified_name.lower() in ["debugcog"]):
            return await self.get_destination().send("❌ Команда не найдена.")

        embed = discord.Embed(title=f"📖 {self.context.prefix}{command.name}", color=discord.Color.blue())
        
        if command.aliases:
            embed.add_field(name="Алиасы", value=", ".join(command.aliases), inline=False)
        
        embed.description = command.help or "Нет описания."
        embed.add_field(name="Использование", value=f"`{self.context.prefix}{command.name} {command.signature}`", inline=False)
        
        await self.get_destination().send(embed=embed)

    async def send_group_help(self, group):
        await self.send_command_help(group)

    async def send_error_message(self, error):
        await self.get_destination().send(embed=discord.Embed(description=error, color=discord.Color.red()))

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._original_help_command = bot.help_command
        bot.help_command = CustomHelp()
        bot.help_command.cog = self
        
    def cog_unload(self):
        self.bot.help_command = self._original_help_command

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
