import discord
import random
from discord.ext import commands

class GamesCommands(commands.Cog):
    """Игровые команды: монетка, дуэли"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.active_duels = {}  # guild_id -> {challenger_id: {opponent_id, bet, msg_id}}
    
    @commands.command(name="flip", aliases=["coinflip", "монетка"])
    async def cmd_flip(self, ctx, bet: int, side: str = "орел"):
        """Подбросить монетку. Использование: /flip <ставка> [орел/решка]"""
        if bet <= 0: return await ctx.send("❌ Ставка должна быть больше 0", delete_after=5)
        
        # Нормализация выбора
        side = side.lower()
        if side not in ["орел", "решка", "heads", "tails", "h", "t", "о", "р"]:
            return await ctx.send("❌ Выберите: орел или решка", delete_after=5)
        
        user_choice = "heads" if side in ["орел", "heads", "h", "о"] else "tails"
        
        # Проверка баланса
        bal = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        if bal < bet:
            return await ctx.send(f"❌ Недостаточно средств! У вас {bal} монет", delete_after=5)
            
        # Защита от полного разорения (оставить минимум 2 монеты)
        if (bal - bet) < 2 and bet > 2:
            return await ctx.send(f"❌ Нельзя уходить в ноль! Оставьте хотя бы 2 монеты.", delete_after=5)
        
        # Логика с подкруткой (55% победы)
        roll = random.random()
        is_win = roll < 0.55
        
        # Если победа -> результат совпадает с выбором
        if is_win:
            result = user_choice
        else:
            result = "tails" if user_choice == "heads" else "heads"
            
        result_emoji = "🪙" if result == "heads" else "💿"
        result_ru = "Орел" if result == "heads" else "Решка"
        
        if is_win:
            await self.db.update_balance(ctx.guild.id, ctx.author.id, bet)
            e = discord.Embed(
                title="🎲 Подбросили монетку!",
                description=f"{result_emoji} **{result_ru}**\n\n✅ **Вы выиграли {bet} монет!**",
                color=discord.Color.green()
            )
        else:
            await self.db.update_balance(ctx.guild.id, ctx.author.id, -bet)
            e = discord.Embed(
                title="🎲 Подбросили монетку!",
                description=f"{result_emoji} **{result_ru}**\n\n❌ **Вы проиграли {bet} монет**",
                color=discord.Color.red()
            )
        
        new_bal = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        e.set_footer(text=f"Ваш баланс: {new_bal} монет")
        await ctx.send(embed=e, delete_after=180)
    
    @commands.command(name="duel", aliases=["дуэль"])
    async def cmd_duel(self, ctx, opponent: discord.Member, bet: int):
        """Вызвать на дуэль. Использование: /duel @пользователь <ставка>"""
        if opponent.bot or opponent.id == ctx.author.id:
            return await ctx.send("❌ Нельзя вызвать себя или бота")
        
        if bet <= 0:
            return await ctx.send("❌ Ставка должна быть больше 0")
        
        # Проверка балансов
        challenger_bal = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        opponent_bal = await self.db.get_balance(ctx.guild.id, opponent.id)
        
        if challenger_bal < bet:
            return await ctx.send(f"❌ У вас недостаточно средств! Нужно {bet}, есть {challenger_bal}")
        
        if opponent_bal < bet:
            return await ctx.send(f"❌ У {opponent.mention} недостаточно средств для этой дуэли")
        
        # Создаём вызов
        class DuelView(discord.ui.View):
            def __init__(self, challenger, opponent_user, bet_amount, db_instance):
                super().__init__(timeout=60)
                self.challenger = challenger
                self.opponent_user = opponent_user
                self.bet = bet_amount
                self.db = db_instance
                self.responded = False
            
            @discord.ui.button(label="⚔️ Принять", style=discord.ButtonStyle.success)
            async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.opponent_user.id:
                    return await interaction.response.send_message("❌ Этот вызов не для вас", ephemeral=True)
                
                if self.responded:
                    return await interaction.response.send_message("❌ Уже отвечено", ephemeral=True)
                
                self.responded = True
                self.stop()
                
                # Бой! Учитываем level и добавляем случайность
                challenger_data = await self.db.get_user(interaction.guild.id, self.challenger.id)
                opponent_data = await self.db.get_user(interaction.guild.id, self.opponent_user.id)
                
                challenger_power = (challenger_data.get('level', 1) * 10) + random.randint(1, 50)
                opponent_power = (opponent_data.get('level', 1) * 10) + random.randint(1, 50)
                
                if challenger_power > opponent_power:
                    winner = self.challenger
                    loser = self.opponent_user
                    win_power = challenger_power
                    lose_power = opponent_power
                else:
                    winner = self.opponent_user
                    loser = self.challenger
                    win_power = opponent_power
                    lose_power = challenger_power
                
                # Обновляем балансы
                await self.db.update_balance(interaction.guild.id, winner.id, self.bet)
                await self.db.update_balance(interaction.guild.id, loser.id, -self.bet)
                
                # Обновляем рейтинги
                await self.db.update_rating(interaction.guild.id, winner.id, 25)
                await self.db.update_rating(interaction.guild.id, loser.id, -15)
                
                e = discord.Embed(
                    title="⚔️ Дуэль завершена!",
                    description=f"**{winner.mention}** одолел **{loser.mention}**!",
                    color=discord.Color.gold()
                )
                e.add_field(name="Сила бойцов", value=f"{self.challenger.mention}: {challenger_power}\n{self.opponent_user.mention}: {opponent_power}")
                e.add_field(name="Выигрыш", value=f"💰 {self.bet} монет\n⭐ +25 рейтинга")
                
                await interaction.response.edit_message(embed=e, view=None)
            
            @discord.ui.button(label="❌ Отказаться", style=discord.ButtonStyle.danger)
            async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.opponent_user.id:
                    return await interaction.response.send_message("❌ Этот вызов не для вас", ephemeral=True)
                
                if self.responded:
                    return await interaction.response.send_message("❌ Уже отвечено", ephemeral=True)
                
                self.responded = True
                self.stop()
                
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        description=f"{self.opponent_user.mention} отказался от дуэли",
                        color=discord.Color.orange()
                    ),
                    view=None
                )
        
        view = DuelView(ctx.author, opponent, bet, self.db)
        
        e = discord.Embed(
            title="⚔️ Вызов на дуэль!",
            description=f"**{ctx.author.mention}** вызывает **{opponent.mention}** на дуэль!\n\n💰 Ставка: **{bet}** монет",
            color=discord.Color.blue()
        )
        e.set_footer(text="У противника есть 60 секунд чтобы ответить")
        
        await ctx.send(embed=e, view=view)

async def setup(bot):
    await bot.add_cog(GamesCommands(bot))
