import discord
import random
import asyncio
import time
from discord.ext import commands
from bot_app.core.dev_manager import dev_manager

class EconomyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def _bypass_cost(self, user_id):
        # Developer in "God Mode" (Debug OFF) -> Free
        if dev_manager.is_god_mode(user_id):
            return True
        return False

    @commands.command(name="daily")
    async def cmd_daily(self, ctx):
        """Получить ежедневный бонус."""
        # Check cooldown
        user_row = await self.db.get_user(ctx.guild.id, ctx.author.id)
        last_claim = user_row.get("daily_last_claim_ts", 0) if user_row else 0
        now = time.time()
        
        # Dev God Mode: Bypass Cooldown
        if self._bypass_cost(ctx.author.id):
            last_claim = 0

        cooldown = 86400 # 24h
        if now - last_claim < cooldown:
            next_ts = int(last_claim + cooldown)
            return await ctx.send(f"⏳ Бонус уже получен. Следующий доступен: <t:{next_ts}:R>")

        config = await self.db.get_config(ctx.guild.id)
        amount = config.get("daily_amount", 100)

        await self.db.claim_daily(ctx.guild.id, ctx.author.id, amount)
        await ctx.send(embed=discord.Embed(
            description=f"🎁 **Ежедневный бонус!** Вы получили **{amount}** монет.", 
            color=discord.Color.green()
        ))

    @commands.command(name="gift")
    async def cmd_gift_phrase(self, ctx, recipient: discord.Member, count: int = 1):
        """Подарить бесплатные проигрывания фраз другому пользователю."""
        if count <= 0: return await ctx.send("Введите число > 0")
        if recipient.bot or recipient.id == ctx.author.id:
            return await ctx.send("Нельзя дарить себе или ботам.")

        # Price per phrase play (e.g. 50 coins)
        price_per_one = 50 
        total_cost = count * price_per_one

        if not self._bypass_cost(ctx.author.id):
            bal = await self.db.get_balance(ctx.guild.id, ctx.author.id)
            if bal < total_cost:
                return await ctx.send(f"❌ Недостаточно средств. Нужно {total_cost}, есть {bal}.")
            await self.db.update_balance(ctx.guild.id, ctx.author.id, -total_cost)

        await self.db.add_free_plays(ctx.guild.id, recipient.id, count)
        
        await ctx.send(embed=discord.Embed(
            description=f"🎁 **{ctx.author.display_name}** подарил {recipient.mention} **{count}** бесплатных фраз!",
            color=discord.Color.purple()
        ))

    @commands.command(name="balance", aliases=["bal", "money"])
    async def cmd_balance(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        u_data = await self.db.get_user(ctx.guild.id, target.id)
        if not u_data:
            # Init user if missing
            await self.db.upsert_user(ctx.guild.id, target.id, target.display_name)
            u_data = {'balance': 0, 'rating': 1000, 'level': 1, 'free_phrase_plays': 0}

        e = discord.Embed(title=f"💳 Кошелек: {target.display_name}", color=discord.Color.gold())
        e.add_field(name="💰 Монеты", value=str(u_data.get('balance', 0)), inline=True)
        e.add_field(name="⭐ Рейтинг", value=str(u_data.get('rating', 1000)), inline=True)
        e.add_field(name="🎁 Фразы", value=str(u_data.get('free_phrase_plays', 0)), inline=True)
        e.set_footer(text=f"Уровень: {u_data.get('level', 1)}")
        await ctx.send(embed=e)

    @commands.command(name="pay")
    async def cmd_pay(self, ctx, recipient: discord.Member, amount: int):
        if recipient.bot or recipient.id == ctx.author.id: return
        if amount <= 0: return

        if not self._bypass_cost(ctx.author.id):
            bal = await self.db.get_balance(ctx.guild.id, ctx.author.id)
            if bal < amount:
                return await ctx.send(f"❌ Недостаточно средств.")
            await self.db.update_balance(ctx.guild.id, ctx.author.id, -amount)

        await self.db.update_balance(ctx.guild.id, recipient.id, amount)
        await ctx.send(embed=discord.Embed(description=f"💸 **{ctx.author.name}** перевел **{amount}** монет {recipient.mention}!", color=discord.Color.green()))

async def setup(bot):
    await bot.add_cog(EconomyCommands(bot))
