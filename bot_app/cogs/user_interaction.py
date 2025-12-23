import discord
from discord.ext import commands
from bot_app.ui.user_menu import UserMenuView

class UserInteraction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="menu")
    async def menu_cmd(self, ctx):
        # Initialize with user-specific context
        view = UserMenuView(self.bot, ctx.author)
        embed = await view._get_main_embed(ctx.guild.id)
        await ctx.send(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(UserInteraction(bot))