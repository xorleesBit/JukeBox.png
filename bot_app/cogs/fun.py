import discord
import random
import datetime
from discord.ext import commands

class FunCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="avatar", aliases=["av"])
    async def get_avatar(self, ctx, target: discord.Member = None):
        """Показать аватарку."""
        target = target or ctx.author
        embed = discord.Embed(title=f"📸 Аватар {target.name}", color=target.color)
        embed.set_image(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="server", aliases=["si"])
    async def server_info(self, ctx):
        """Информация о сервере."""
        g = ctx.guild
        embed = discord.Embed(title=f"🏰 {g.name}", color=discord.Color.gold())
        if g.icon: embed.set_thumbnail(url=g.icon.url)
        
        embed.add_field(name="Владелец", value=g.owner.mention, inline=True)
        embed.add_field(name="ID", value=g.id, inline=True)
        embed.add_field(name="Участников", value=str(g.member_count), inline=True)
        embed.add_field(name="Создан", value=f"<t:{int(g.created_at.timestamp())}:R>", inline=True)
        
        bots = sum(1 for m in g.members if m.bot)
        embed.add_field(name="Люди / Боты", value=f"{g.member_count - bots} / {bots}", inline=True)
        
        await ctx.send(embed=embed)

    @commands.command(name="poll")
    async def create_poll(self, ctx, question: str, *options):
        """Создать опрос: !poll "Вопрос" "Вариант1" "Вариант2"..."""
        if len(options) < 2:
            return await ctx.send("❌ Нужно минимум 2 варианта ответа.")
        if len(options) > 10:
            return await ctx.send("❌ Максимум 10 вариантов.")
            
        emoji_nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        desc = ""
        for i, opt in enumerate(options):
            desc += f"{emoji_nums[i]} {opt}\n"
            
        embed = discord.Embed(title=f"📊 {question}", description=desc, color=discord.Color.blurple())
        embed.set_footer(text=f"Автор: {ctx.author.name}")
        
        msg = await ctx.send(embed=embed)
        for i in range(len(options)):
            await msg.add_reaction(emoji_nums[i])

async def setup(bot):
    await bot.add_cog(FunCog(bot))