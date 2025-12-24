import discord
from discord.ext import commands
from bot_app.ui.user_menu import UserMenuView

class UserInteraction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="menu")
    async def menu_cmd(self, ctx):
        # 1. Delete user command
        try: await ctx.message.delete()
        except: pass

        # 2. Send menu (public but limited to user ID in interaction_check)
        view = UserMenuView(self.bot, ctx.author)
        embed = await view._get_main_embed(ctx.guild.id)
        # Main menu message will auto-delete after 5 mins to keep chat clean
        await ctx.send(embed=embed, view=view, delete_after=300)

async def setup(bot):
    await bot.add_cog(UserInteraction(bot))