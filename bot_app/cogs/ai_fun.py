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

        # BUFF CHECK: Anti-Roast
        if hasattr(self.bot, 'buff_manager'):
            has_shield = await self.bot.buff_manager.has_buff(ctx.guild.id, target.id, "anti_roast")
            if has_shield:
                await ctx.send(f"🛡️ **{target.display_name}** защищен Зеркалом! Прожарка отражается на вас! 😈")
                target = ctx.author # Reflect

        msg = await ctx.send(f"🤖 Собираю компромат на {target.display_name}...")
        
        # 1. Collect Logs
        lc = LogContext(ctx.guild.id, ctx.guild.name)
        logs = lc.get_user_logs(target.display_name, limit=150, days_lookback=5)
        
        if not logs or len(logs) < 50:
             return await msg.edit(content="❌ Слишком мало данных в логах (нужно общение в голосе или чате за последние 5 дней).")

        # 2. Charge
        if not bypass:
            await self.bot.db.update_balance(ctx.guild.id, ctx.author.id, -cost)

        # 3. AI Request
        await msg.edit(content="🔥 Генерирую прожарку... (Монеты списаны)")
        
        sys_prompt = (
            "Ты — стендап-комик. Твоя задача — прожарить пользователя на основе его ЛОГОВ (истории сообщений).\n"
            "Правила:\n"
            "1. Не шути про никнейм, если в логах есть о чем поговорить.\n"
            "2. Ищи странные фразы, повторы, глупые вопросы, капс или эмоции.\n"
            "3. Если логов мало или они скучные — пошути над тем, что он 'молчун' или 'NPC'.\n"
            "4. Будь едким, но не оскорбляй (roast, not bullying).\n"
            "Отвечай на русском."
        )
        
        user_prompt = f"Пользователь: {target.display_name}\nЛоги:\n{logs}\n\nПрожарка:"
        
        response = await ask_ai(user_prompt, sys_prompt)
        
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
        logs = lc.get_user_logs(target.display_name, limit=100, days_lookback=5)
        
        if not logs or len(logs) < 50:
            return await msg.edit(content="❌ Недостаточно данных для шутки (минимум общения за 5 дней).")
            
        if not bypass:
            await self.bot.db.update_balance(ctx.guild.id, ctx.author.id, -cost)

        sys_prompt = (
            "Ты — добрый и остроумный друг. Твоя задача — придумать смешную, но добрую шутку или анекдот про пользователя, основываясь на теме его разговоров.\n"
            "Правила:\n"
            "1. Не шути про никнейм. Анализируй текст его сообщений.\n"
            "2. Найди тему разговора (игры, фильмы, учеба) и пошути на эту тему.\n"
            "3. Если контекст непонятен, придумай общую шутку про Discord или геймеров.\n"
            "4. Важно: Шутка должна быть позитивной. Без сарказма и негатива."
        )
        user_prompt = f"Пользователь: {target.display_name}\nЕго реплики:\n{logs}\n\nШутка:"
        
        response = await ask_ai(user_prompt, sys_prompt)
        
        embed = discord.Embed(title=f"🤡 Шутка про {target.display_name}", description=response, color=discord.Color.gold())
        embed.set_footer(text=f"Цена: {cost} монет")
        
        await msg.delete()
        await ctx.send(embed=embed)

    @commands.command(name="month_recap")
    async def cmd_month_recap(self, ctx):
        """AI отчет за текущий месяц (на основе архивов)."""
        cost = 1000
        from bot_app.core.dev_manager import dev_manager
        
        if not dev_manager.is_god_mode(ctx.author.id):
            bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
            if bal < cost: return await ctx.send(f"❌ Цена: {cost} монет.")
            await self.bot.db.update_balance(ctx.guild.id, ctx.author.id, -cost)

        msg = await ctx.send("📅 Анализирую архивы месяца...")
        
        # Find summaries
        import os
        from bot_app.core.config import LOG_DIR
        from bot_app.core.utils import safe_dirname
        
        g_dir = safe_dirname(ctx.guild.name)
        archive_path = os.path.join(LOG_DIR, "archives", g_dir)
        
        if not os.path.exists(archive_path):
            return await msg.edit(content="❌ Нет архивов.")
            
        # Filter current month
        # Filename: data-YYYY-MM-DD_to_... .txt
        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m") # 2025-12
        
        summaries = []
        for f in os.listdir(archive_path):
            if f.endswith("_summary.md") and now_str in f:
                try:
                    with open(os.path.join(archive_path, f), "r", encoding="utf-8") as md:
                        summaries.append(md.read())
                except: pass
                
        if not summaries:
            return await msg.edit(content="❌ Нет данных за этот месяц (возможно, архивация еще не прошла).")
            
        full_text = "\n\n".join(summaries)
        
        # Send to AI
        await msg.edit(content="🧠 Генерирую Итоги Месяца...")
        
        prompt = (
            f"Проанализируй отчеты сервера '{ctx.guild.name}' и напиши ИТОГОВЫЙ ДАЙДЖЕСТ месяца.\n"
            "Входные данные (Markdown отчеты по неделям):\n" + full_text + "\n\n"
            "ЗАДАЧА:\n"
            "1. Кратко перескажи главные события (что обсуждали, во что играли).\n"
            "2. Выдели 'Героев месяца' (кто больше всех говорил или шутил), основываясь ТОЛЬКО на тексте.\n"
            "3. Стиль: Легкий, юмористический, как в молодежном журнале или блоге.\n"
            "4. ВАЖНО: Не выдумывай события. Если данных нет — так и напиши ('Месяц был тихим').\n"
            "Ответ в Markdown."
        )
        
        res = await ask_ai(prompt)
        
        # Save or Send? Too big for embed?
        # Send as file + short embed
        with open("month_recap.md", "w", encoding="utf-8") as f:
            f.write(res)
            
        await msg.delete()
        await ctx.send(f"🏆 **Итоги Месяца**", file=discord.File("month_recap.md"))
        os.remove("month_recap.md")

async def setup(bot):
    await bot.add_cog(AIFunCog(bot))