import discord
from discord.ext import commands
from bot_app.ui.user_menu import UserMenuView
from bot_app.ui.profile_menu import ProfileView
from bot_app.core.state import profile_manager

class UserInteraction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="profile")
    async def profile_cmd(self, ctx):
        """Настройка профиля для ИИ (Имя, Пол, Биография)"""
        try: await ctx.message.delete()
        except: pass
        
        p = await profile_manager.get_profile(ctx.guild.id, ctx.author.id)
        
        # Build Info Embed
        name = p['real_name'] or ctx.author.display_name
        gender = p['gender']
        bio = p['bio'] or "Нет"
        
        e = discord.Embed(title=f"👤 Профиль: {ctx.author.display_name}", color=discord.Color.blue())
        e.add_field(name="Имя для ИИ", value=name, inline=True)
        e.add_field(name="Пол", value=gender, inline=True)
        e.add_field(name="Лор / О себе", value=bio, inline=False)
        e.set_footer(text="Используйте кнопки ниже для редактирования")
        
        await ctx.send(embed=e, view=ProfileView(ctx.guild.id, ctx.author.id), delete_after=120)

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