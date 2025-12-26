import discord
from discord.ext import commands
from bot_app.features.news_generator import generate_news_json
from bot_app.ui.ui import PhraseSelect
from bot_app.ui.ui import PhraseSelect

class GeneralCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.loggers = bot.loggers

    @commands.command(name="clearchat")
    @commands.has_permissions(manage_messages=True)
    async def cmd_clearchat(self, ctx, limit: int = 100):
        try:
            await ctx.channel.purge(limit=limit)
            e = discord.Embed(description="🧹 Чат очищен.", color=discord.Color.green())
            await ctx.send(embed=e, delete_after=5)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"Ошибка: {e}", color=discord.Color.red()), delete_after=10)

    async def _send_news(self, ctx, days):
        status_msg = await ctx.send(embed=discord.Embed(description=f"📰 Анализируем {days} дн...", color=discord.Color.blue()))
        try:
            data = await generate_news_json(ctx.guild.id, ctx.guild.name, days=days)
            
            if "error" in data:
                await ctx.send(embed=discord.Embed(description=f"❌ {data['error']}", color=discord.Color.red()))
            else:
                headline = data.get("headline", "НОВОСТИ")
                article = data.get("article", "...")
                hero = data.get("hero", "Неизвестный")
                quote = data.get("quote", "...")
                summary = data.get("summary", [])
                
                e = discord.Embed(title=f"🗞️ {headline}", description=article[:4000], color=discord.Color.gold())
                if summary:
                    summary_text = "\n".join([f"• {s}" for s in summary])
                    e.add_field(name="📌 Главное", value=summary_text, inline=False)
                e.add_field(name="👑 Герой", value=hero, inline=True)
                e.add_field(name="💬 Цитата", value=f"*{quote}*", inline=True)
                e.set_footer(text=f"Server News ({days} days) | {ctx.guild.name}")
                await ctx.send(embed=e)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"Ошибка: {e}", color=discord.Color.red()))
        try: await status_msg.delete() 
        except: pass

    @commands.command(name="news")
    async def cmd_news(self, ctx, days: int = 1):
        """Новости за указанное количество дней (по умолчанию 1)."""
        if days < 1: days = 1
        if days > 7: days = 7
        await self._send_news(ctx, days=days)

    @commands.command(name="top")
    async def cmd_top(self, ctx):
        rows = await self.db.get_top_users(ctx.guild.id, limit=10)
        if not rows: return await ctx.send(embed=discord.Embed(description="Нет данных.", color=discord.Color.orange()), delete_after=20)
        desc = ""
        for i, r in enumerate(rows, 1):
            m = ctx.guild.get_member(r['user_id'])
            name = m.mention if m else f"User {r['user_id']}"
            desc += f"**{i}.** {name} — 🎖️ {r['level']} | ⭐ {r['rating']} | 💰 {r['balance']}\n"
        await ctx.send(embed=discord.Embed(title="🏆 Топ Лидеров", description=desc, color=discord.Color.gold()), delete_after=180)

    @commands.command(name="profile")
    async def cmd_profile(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        u_data = await self.db.get_user(ctx.guild.id, target.id)
        if not u_data: return await ctx.send(embed=discord.Embed(description="Профиль не найден.", color=discord.Color.red()))
        p_data = await self.db.get_profile(ctx.guild.id, target.id)
        
        e = discord.Embed(title=f"👤 Профиль: {target.display_name}", color=target.color or discord.Color.blurple())
        e.set_thumbnail(url=target.display_avatar.url)
        
        lvl = u_data['level'] or 1
        xp = u_data['xp'] or 0
        bal = u_data['balance'] or 0
        rat = u_data['rating'] or 1000
        stats = f"🎖️ **Уровень:** {lvl} ({xp} XP)\n💰 **Баланс:** {bal}\n⭐ **Рейтинг:** {rat}"
        e.add_field(name="Статистика", value=stats, inline=False)
        
        if p_data:
            pers = p_data.get('personality', 'Не определено')
            e.add_field(name="🧠 Характер", value=pers, inline=False)
            interests = p_data.get('interests', [])
            if interests: e.add_field(name="💡 Интересы", value=", ".join(interests)[:1024], inline=True)
            games = p_data.get('games', [])
            if games: e.add_field(name="🎮 Игры", value=", ".join(games)[:1024], inline=True)
            phrases = p_data.get('favorite_phrases', [])
            if phrases:
                ph_text = "\n".join([f"• {p}" for p in phrases[:5]])
                e.add_field(name="🗣️ Любимые фразы", value=ph_text[:1024], inline=False)
            relations = p_data.get('relations', {})
            if relations:
                rel_list = []
                for k, v in relations.items():
                    if k.isdigit(): rel_list.append(f"<@{k}>: {v}")
                    else: rel_list.append(f"**{k}**: {v}")
                e.add_field(name="💞 Отношения", value="\n".join(rel_list)[:1024], inline=False)
            
            achievements = p_data.get('achievements', [])
            if achievements:
                last_3 = achievements[-3:]
                ach_list = [f"🏅 **{a.get('title')}**: {a.get('desc')}" for a in last_3]
                e.add_field(name=f"🏆 Достижения ({len(achievements)})", value="\n".join(ach_list), inline=False)
        else:
             # Just init variable if no profile
             achievements = []

        # Interactive View for Profile
        class ProfileView(discord.ui.View):
            def __init__(self, bot, guild_id, user_id):
                super().__init__(timeout=60)
                self.bot = bot
                self.guild_id = guild_id
                self.user_id = user_id

            @discord.ui.button(label="Магазин", emoji="🛒", style=discord.ButtonStyle.primary)
            async def btn_shop(self, interaction: discord.Interaction, _):
                # Import here to avoid circular
                from bot_app.ui.shop_menu import ShopView
                await interaction.response.send_message("🛒 **Магазин**", view=ShopView(self.bot.db, self.guild_id), ephemeral=True)

            @discord.ui.button(label="Инвентарь", emoji="🎒", style=discord.ButtonStyle.secondary)
            async def btn_inv(self, interaction: discord.Interaction, _):
                from bot_app.ui.inventory_menu import InventoryView
                from bot_app.ui.inventory_menu import InventoryView as InventoryViewUI
                view = InventoryViewUI(self.bot.db, self.guild_id, interaction.user.id)
                await view.send_ephemeral(interaction)

            @discord.ui.button(label="Daily", emoji="🎁", style=discord.ButtonStyle.success)
            async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.user_id:
                     return await interaction.response.send_message("Это не ваш профиль.", ephemeral=True)
                
                # Check Last Daily
                last_daily = await self.bot.db.get_last_daily(self.guild_id, self.user_id)
                now = discord.utils.utcnow().timestamp()
                # 24h = 86400
                if last_daily and (now - last_daily < 86400):
                    rem = int(86400 - (now - last_daily))
                    h = rem // 3600
                    m = (rem % 3600) // 60
                    await interaction.response.send_message(f"⏳ Рано! Жди {h}ч {m}м.", ephemeral=True)
                else:
                    bonus = 100 # Configurable?
                    await self.bot.db.update_balance(self.guild_id, self.user_id, bonus)
                    await self.bot.db.set_last_daily(self.guild_id, self.user_id, now)
                    button.disabled = True
                    button.label = "Забрано"
                    await interaction.response.edit_message(view=self)
                    await interaction.followup.send(f"🎁 Вы получили ежедневный бонус: **{bonus} монет**!", ephemeral=True)

        # Show buttons only if viewing own profile 
        view = None
        if ctx.author.id == target.id:
            view = ProfileView(self.bot, ctx.guild.id, ctx.author.id)

        await ctx.send(embed=e, view=view, delete_after=300)



    @commands.command(name="achs")
    async def cmd_achs(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        p_data = await self.db.get_profile(ctx.guild.id, target.id)
        achs = p_data.get('achievements', []) if p_data else []
        
        if not achs:
            return await ctx.send(embed=discord.Embed(description=f"У {target.mention} пока нет достижений.", color=discord.Color.orange()))
            
        e = discord.Embed(title=f"🏅 Достижения: {target.display_name}", color=discord.Color.gold())
        
        for a in achs[-10:]:
            title = a.get('title', 'Награда')
            desc = a.get('desc', '')
            date = a.get('date', '')
            e.add_field(name=f"{title} ({date})", value=desc, inline=False)
            
        await ctx.send(embed=e)

    @commands.command(name="phrases")
    async def cmd_phrases(self, ctx, user_id: str = None):
        target_id = ctx.author.id
        if user_id:
            try: target_id = int(''.join(filter(str.isdigit, user_id)))
            except: pass
        
        phrases = await self.db.get_all_user_phrases(ctx.guild.id, target_id, limit=25)
        if not phrases:
            return await ctx.send(embed=discord.Embed(description="Нет фраз.", color=discord.Color.red()))

        logger = self.loggers.get(ctx.guild.id)
        view = discord.ui.View()
        view.add_item(PhraseSelect(phrases, self.db, logger))
        await ctx.send(embed=discord.Embed(description=f"Фразы <@{target_id}>:"), view=view, delete_after=60)
    
    @commands.command(name="words", aliases=["слова"])
    async def cmd_words(self, ctx, member: discord.Member = None):
        """Статистика слов пользователя"""
        target = member or ctx.author
        stats = await self.db.get_word_stats(ctx.guild.id, target.id, limit=15)
        
        if not stats:
            return await ctx.send(embed=discord.Embed(
                description=f"У {target.mention} пока нет статистики слов.",
                color=discord.Color.orange()
            ))
        
        # Общее количество слов
        u_data = await self.db.get_user(ctx.guild.id, target.id)
        total_words = u_data.get('words_audio', 0) if u_data else 0
        
        e = discord.Embed(
            title=f"📝 Статистика слов: {target.display_name}",
            description=f"Всего произнесено: **{total_words}** слов",
            color=target.color or discord.Color.blurple()
        )
        e.set_thumbnail(url=target.display_avatar.url)
        
        # Топ слов
        top_list = []
        for i, row in enumerate(stats, 1):
            word = row['word']
            count = row['count']
            bar_length = min(int(count / stats[0]['count'] * 20), 20)
            bar = "█" * bar_length + "░" * (20 - bar_length)
            top_list.append(f"`{i:2d}.` **{word}** {bar} `{count}`")
        
        e.add_field(name="🏆 Топ слов", value="\n".join(top_list), inline=False)
        e.set_footer(text=f"Показаны топ {len(stats)} слов")
        
        await ctx.send(embed=e)

async def setup(bot):
    await bot.add_cog(GeneralCommands(bot))