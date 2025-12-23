import discord
from discord.ext import commands
from bot_app.core.utils import has_balance
from bot_app.integrations.ai_client import ask_ai
from bot_app.features.log_context import LogContext

class AIFunCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_cost(self, guild_id):
        cfg = await self.bot.db.get_config(guild_id)
        return cfg.get("ai_roast_price", 500)

    @commands.command(name="roast")
    async def cmd_roast(self, ctx, target: discord.Member = None):
        """AI прожарка пользователя на основе его логов (Платно)."""
        target = target or ctx.author
        cost = await self._get_cost(ctx.guild.id)
        
        # Check balance manually to deduct later
        from bot_app.core.dev_manager import dev_manager
        bypass = dev_manager.is_god_mode(ctx.author.id)
        
        if not bypass:
            bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
            if bal < cost:
                return await ctx.send(f"❌ Нужно {cost} монет. У вас {bal}.")

        msg = await ctx.send(f"🤖 Собираю компромат на {target.display_name}...")
        
        # 1. Collect Logs
        lc = LogContext(ctx.guild.id, ctx.guild.name)
        logs = lc.get_user_logs(target.display_name, limit=150)
        
        if not logs or len(logs) < 50:
             return await msg.edit(content="❌ Слишком мало данных в логах (нужно общение в голосе или чате за последние 24ч).")

        # 2. Charge
        if not bypass:
            await self.bot.db.update_balance(ctx.guild.id, ctx.author.id, -cost)

        # 3. AI Request
        await msg.edit(content="🔥 Генерирую прожарку... (Монеты списаны)")
        
        sys_prompt = (
            "Ты — ехидный стендап-комик. Твоя задача — жестко, но смешно 'прожарить' (roast) пользователя, "
            "основываясь на истории его сообщений. Используй сленг, сарказм, иронию. "
            "Не будь слишком токсичным, но будь метким. "
            "Отвечай на русском языке."
        )
        
        user_prompt = f"Пользователь: {target.display_name}\nЛоги его общения:\n{logs}\n\nНапиши прожарку."
        
        response = await ask_ai(user_prompt, system_prompt)
        
        embed = discord.Embed(title=f"🔥 Roast: {target.display_name}", description=response, color=discord.Color.dark_orange())
        embed.set_footer(text=f"Заказал: {ctx.author.display_name} | -{cost} монет")
        
        await msg.delete()
        await ctx.send(embed=embed)

    @commands.command(name="joke")
    async def cmd_joke(self, ctx, target: discord.Member = None):
        """Добрая AI шутка про пользователя (Платно)."""
        target = target or ctx.author
        cost = await self._get_cost(ctx.guild.id) // 2 # Cheaper
        
        from bot_app.core.dev_manager import dev_manager
        bypass = dev_manager.is_god_mode(ctx.author.id)

        if not bypass:
            bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
            if bal < cost:
                return await ctx.send(f"❌ Нужно {cost} монет. У вас {bal}.")

        msg = await ctx.send(f"🤖 Придумываю шутку про {target.display_name}...")
        
        lc = LogContext(ctx.guild.id, ctx.guild.name)
        logs = lc.get_user_logs(target.display_name, limit=100)
        
        if not bypass:
            await self.bot.db.update_balance(ctx.guild.id, ctx.author.id, -cost)

        sys_prompt = "Ты веселый друг. Придумай добрую шутку или анекдот про пользователя, используя контекст его фраз."
        user_prompt = f"Пользователь: {target.display_name}\nЛоги:\n{logs}\n\nШутка:"
        
        response = await ask_ai(user_prompt, sys_prompt)
        
        embed = discord.Embed(title=f"🤡 Шутка: {target.display_name}", description=response, color=discord.Color.gold())
        embed.set_footer(text=f"Цена: {cost} монет")
        
        await msg.delete()
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AIFunCog(bot))