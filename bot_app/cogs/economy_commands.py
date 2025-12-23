import discord
import random
import asyncio
from discord.ext import commands

class FlipRebetView(discord.ui.View):
    def __init__(self, db, user_id: int, side_idx: int, amount: int):
        super().__init__(timeout=30)
        self.db = db
        self.user_id = user_id
        self.side_idx = side_idx
        self.amount = amount

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Это не ваша игра.", ephemeral=True)
            return False
        return True

    async def _run_flip(self, interaction: discord.Interaction, bet_amount: int):
        bal = await self.db.get_balance(interaction.guild_id, self.user_id)
        if bet_amount >= bal: bet_amount = bal
        if bet_amount <= 0:
            return await interaction.response.send_message("Вам нужно минимум 1 монета.", ephemeral=True)
        
        await self.db.update_balance(interaction.guild_id, self.user_id, -bet_amount)
        result_val = random.randint(0, 1)
        result_str = "Орел 🦅" if result_val == 0 else "Решка 🪙"
        win = (result_val == self.side_idx)
        
        msg = ""
        color = discord.Color.red()
        if win:
            win_amount = bet_amount * 2
            await self.db.update_balance(interaction.guild_id, self.user_id, win_amount)
            msg = f"**{result_str}!** Вы выиграли {bet_amount}! (Баланс: {bal + bet_amount})"
            color = discord.Color.green()
        else:
            msg = f"**{result_str}.** Вы проиграли {bet_amount}. (Баланс: {bal - bet_amount})"
        
        new_view = FlipRebetView(self.db, self.user_id, self.side_idx, bet_amount)
        await interaction.response.edit_message(embed=discord.Embed(description=msg, color=color), view=new_view)

    @discord.ui.button(label="Повторить ставку", style=discord.ButtonStyle.primary)
    async def bet_same(self, interaction: discord.Interaction, _):
        await self._run_flip(interaction, self.amount)

    @discord.ui.button(label="Ва-банк (все)", style=discord.ButtonStyle.danger)
    async def bet_all(self, interaction: discord.Interaction, _):
        bal = await self.db.get_balance(interaction.guild_id, self.user_id)
        await self._run_flip(interaction, bal)

class EconomyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @commands.command(name="balance", aliases=["bal", "money"])
    async def cmd_balance(self, ctx, member: discord.Member = None):
        """Показать баланс."""
        target = member or ctx.author
        u_data = await self.db.get_user(ctx.guild.id, target.id)
        if not u_data:
            return await ctx.send(embed=discord.Embed(description="Нет данных.", color=discord.Color.red()))

        e = discord.Embed(title=f"💳 Кошелек: {target.display_name}", color=discord.Color.gold())
        e.add_field(name="💰 Монеты", value=str(u_data['balance']), inline=True)
        e.add_field(name="⭐ Рейтинг", value=str(u_data['rating']), inline=True)
        e.set_footer(text=f"Уровень: {u_data['level']}")
        await ctx.send(embed=e)

    @commands.command(name="pay")
    async def cmd_pay(self, ctx, recipient: discord.Member, amount: int):
        if recipient.bot or recipient.id == ctx.author.id: return
        if amount <= 0: return

        bal = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        if bal < amount:
            return await ctx.send(embed=discord.Embed(description="Недостаточно средств.", color=discord.Color.red()))

        await self.db.update_balance(ctx.guild.id, ctx.author.id, -amount)
        await self.db.update_balance(ctx.guild.id, recipient.id, amount)
        await ctx.send(embed=discord.Embed(description=f"💸 **{ctx.author.name}** перевел **{amount}** монет {recipient.mention}!", color=discord.Color.green()))

    @commands.command(name="flip")
    async def cmd_flip(self, ctx, side: str, amount: str):
        s = side.lower().strip()
        target_val = 0 if s in ["heads", "h", "орел", "о"] else (1 if s in ["tails", "t", "решка", "р"] else -1)
        if target_val == -1: return

        bal = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        bet = bal if amount.lower() in ["all", "vse", "все"] else 0
        if bet == 0:
            try: bet = int(amount)
            except: return

        if bet <= 0 or bet > bal: return

        await self.db.update_balance(ctx.guild.id, ctx.author.id, -bet)
        result_val = random.randint(0, 1)
        result_str = "Орел 🦅" if result_val == 0 else "Решка 🪙"
        view = FlipRebetView(self.db, ctx.author.id, target_val, bet)
        
        win = (result_val == target_val)
        win_amount = bet * 2
        
        color = discord.Color.green() if win else discord.Color.red()
        msg = ""
        if win:
            await self.db.update_balance(ctx.guild.id, ctx.author.id, win_amount)
            msg = f"**{result_str}!** Победа! (+{bet})"
        else:
            msg = f"**{result_str}.** Поражение. (-{bet})"
            
        await ctx.send(embed=discord.Embed(description=msg, color=color), view=view)

    @commands.command(name="duel")
    async def cmd_duel(self, ctx, opponent: discord.Member, amount: int):
        if opponent.bot or opponent.id == ctx.author.id: return
        if amount <= 0: return

        bal_a = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        bal_b = await self.db.get_balance(ctx.guild.id, opponent.id)
        if bal_a < amount or bal_b < amount:
            return await ctx.send(embed=discord.Embed(description="У кого-то не хватает денег.", color=discord.Color.red()))

        msg = await ctx.send(f"{opponent.mention}", embed=discord.Embed(description=f"⚔️ **{ctx.author.name}** вызывает вас на дуэль на **{amount}** монет! Напишите `accept`.", color=discord.Color.orange()))
        
        def check(m): return m.author == opponent and m.channel == ctx.channel and m.content.lower() == "accept"
        try: await self.bot.wait_for("message", check=check, timeout=30.0)
        except asyncio.TimeoutError: return await ctx.send(embed=discord.Embed(description="Дуэль отменена.", color=discord.Color.dark_grey()))

        bal_a = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        bal_b = await self.db.get_balance(ctx.guild.id, opponent.id)
        if bal_a < amount or bal_b < amount: return

        # Logic
        rating_a = await self.db.get_rating(ctx.guild.id, ctx.author.id)
        rating_b = await self.db.get_rating(ctx.guild.id, opponent.id)
        prob_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
        
        roll = random.random()
        winner = ctx.author if roll < prob_a else opponent
        loser = opponent if winner == ctx.author else ctx.author
        
        await self.db.update_balance(ctx.guild.id, winner.id, amount)
        await self.db.update_balance(ctx.guild.id, loser.id, -amount)
        await self.db.update_rating(ctx.guild.id, winner.id, 25)
        await self.db.update_rating(ctx.guild.id, loser.id, -25)
        
        e = discord.Embed(title="⚔️ Результаты Дуэли", color=discord.Color.gold())
        e.add_field(name="Победитель", value=f"{winner.mention}\n+{amount} монет", inline=True)
        e.add_field(name="Шанс", value=f"{int(prob_a*100)}%", inline=True)
        await ctx.send(embed=e)

async def setup(bot):
    await bot.add_cog(EconomyCommands(bot))