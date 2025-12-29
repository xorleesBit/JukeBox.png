import discord
from discord.ext import commands
from bot_app.features.news_generator import generate_news_json
from bot_app.ui.ui import PhraseSelect
from bot_app.ui.common import send_success, send_error, send_info, send_warning, send_embed

class GeneralCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.loggers = bot.loggers

    @commands.command(name="clearchat")
    @commands.has_permissions(manage_messages=True)
    async def cmd_clearchat(self, ctx, limit: int = 100):
        await ctx.channel.purge(limit=limit)
        await send_success(ctx, "Чат очищен.", delete_after=5)

    async def _send_news(self, ctx, days):
        status_msg = await ctx.send(embed=discord.Embed(description=f"📰 Анализируем последние {days} дн...", color=discord.Color.blue()))
        
        data = await generate_news_json(ctx.guild.id, ctx.guild.name, days=days)
        
        # Try to delete loading message
        try: await status_msg.delete() 
        except: pass

        if "error" in data:
            return await send_error(ctx, data['error'])
            
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

    @commands.command(name="news")
    async def cmd_news(self, ctx, days: int = 1):
        """Новости за указанное количество дней (по умолчанию 1)."""
        if days < 1: days = 1
        if days > 7: days = 7
        await self._send_news(ctx, days=days)

    @commands.command(name="top")
    async def cmd_top(self, ctx):
        rows = await self.db.get_top_users(ctx.guild.id, limit=10)
        if not rows: 
            return await send_warning(ctx, "Нет данных для топа.")
            
        desc = ""
        for i, r in enumerate(rows, 1):
            m = ctx.guild.get_member(r['user_id'])
            name = m.mention if m else f"User {r['user_id']}"
            desc += f"**{i}.** {name} — 🎖️ {r['level']} | ⭐ {r['rating']} | 💰 {r['balance']}\n"
        
        await send_embed(ctx, "🏆 Топ Лидеров", desc, discord.Color.gold(), delete_after=180)

    @commands.command(name="stats", aliases=["stat", "me"])
    async def cmd_stats(self, ctx, member: discord.Member = None):
        """Показать статистику (XP, баланс, уровень)."""
        target = member or ctx.author
        
        user_data = await self.db.get_user(ctx.guild.id, target.id)
        if not user_data:
            # Init if missing
            await self.db.upsert_user(ctx.guild.id, target.id, target.display_name)
            user_data = await self.db.get_user(ctx.guild.id, target.id)
            
        e = discord.Embed(title=f"📊 Статистика: {target.display_name}", color=discord.Color.green())
        e.set_thumbnail(url=target.display_avatar.url)
        
        # Level Bar logic
        xp = user_data['xp']
        lvl = user_data['level']
        next_xp = (lvl ** 2) * 150
        
        e.add_field(name="Уровень", value=f"**{lvl}** ({xp}/{next_xp} XP)", inline=True)
        e.add_field(name="Баланс", value=f"💰 {user_data['balance']}", inline=True)
        e.add_field(name="Рейтинг", value=f"📈 {user_data['rating']}", inline=True)
        
        # Word stats
        w_text = user_data['words_text_total']
        w_audio = user_data['words_audio_total']
        e.add_field(name="Слов сказано", value=f"💬 {w_text} (чат) | 🎤 {w_audio} (войс)", inline=False)
        
        # Inline View Class (kept here for now, but cleaner)
        class StatsViewInternal(discord.ui.View):
            def __init__(self, bot, guild_id, user_id):
                super().__init__(timeout=60)
                self.bot = bot
                self.guild_id = guild_id
                self.user_id = user_id

            @discord.ui.button(label="Магазин", emoji="🛒", style=discord.ButtonStyle.primary)
            async def btn_shop(self, interaction: discord.Interaction, _):
                from bot_app.ui.shop_menu import ShopView
                await interaction.response.send_message("🛒 **Магазин**", view=ShopView(self.bot.db, self.guild_id), ephemeral=True)

            @discord.ui.button(label="Инвентарь", emoji="🎒", style=discord.ButtonStyle.secondary)
            async def btn_inv(self, interaction: discord.Interaction, _):
                from bot_app.ui.inventory_menu import InventoryView as InventoryViewUI
                view = InventoryViewUI(self.bot.db, self.guild_id, interaction.user.id)
                await view.send_ephemeral(interaction)

            @discord.ui.button(label="Daily", emoji="🎁", style=discord.ButtonStyle.success)
            async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.user_id:
                     return await interaction.response.send_message("Это не ваша статистика.", ephemeral=True)
                
                last_daily = await self.bot.db.get_last_daily(self.guild_id, self.user_id)
                now = discord.utils.utcnow().timestamp()
                
                if last_daily and (now - last_daily < 86400):
                    rem = int(86400 - (now - last_daily))
                    h = rem // 3600
                    m = (rem % 3600) // 60
                    await interaction.response.send_message(f"⏳ Рано! Жди {h}ч {m}м.", ephemeral=True)
                else:
                    bonus = 100 
                    await self.bot.db.update_balance(self.guild_id, self.user_id, bonus)
                    await self.bot.db.set_last_daily(self.guild_id, self.user_id, now)
                    button.disabled = True
                    button.label = "Забрано"
                    await interaction.response.edit_message(view=self)
                    await interaction.followup.send(f"🎁 Вы получили ежедневный бонус: **{bonus} монет**!", ephemeral=True)

        view = None
        if ctx.author.id == target.id:
            view = StatsViewInternal(self.bot, ctx.guild.id, ctx.author.id)

        await ctx.send(embed=e, view=view, delete_after=300)

    @commands.command(name="achs")
    async def cmd_achs(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        p_data = await self.db.get_profile(ctx.guild.id, target.id)
        achs = p_data.get('achievements', []) if p_data else []
        
        if not achs:
            return await send_info(ctx, f"У {target.mention} пока нет достижений.")
            
        e = discord.Embed(title=f"🏅 Достижения: {target.display_name}", color=discord.Color.gold())
        for a in achs[-10:]:
            e.add_field(name=f"{a.get('title', 'Награда')} ({a.get('date', '')})", value=a.get('desc', ''), inline=False)
            
        await ctx.send(embed=e)

    @commands.command(name="phrases")
    async def cmd_phrases(self, ctx, user_id: str = None):
        target_id = ctx.author.id
        if user_id:
            try: target_id = int(''.join(filter(str.isdigit, user_id)))
            except: pass
        
        phrases = await self.db.get_all_user_phrases(ctx.guild.id, target_id, limit=25)
        if not phrases:
            return await send_warning(ctx, "Нет сохраненных фраз.")

        logger = self.loggers.get(ctx.guild.id)
        view = discord.ui.View()
        view.add_item(PhraseSelect(phrases, self.db, logger))
        
        await ctx.send(embed=discord.Embed(description=f"Фразы <@{target_id}>"), view=view, delete_after=60)
    
    @commands.command(name="words", aliases=["слова"])
    async def cmd_words(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        stats = await self.db.get_word_stats(ctx.guild.id, target.id, limit=15)
        
        if not stats:
            return await send_info(ctx, f"У {target.mention} пока нет статистики слов.")
        
        u_data = await self.db.get_user(ctx.guild.id, target.id)
        # Fix: Use correct DB key 'words_audio_total'
        total_words = u_data.get('words_audio_total', 0) if u_data else 0
        
        from bot_app.core.text_utils import declension
        word_form = declension(total_words, "слово", "слова", "слов")
        
        e = discord.Embed(
            title=f"📝 Статистика: {target.display_name}",
            description=f"Всего произнесено: **{total_words}** {word_form}",
            color=target.color or discord.Color.blurple()
        )
        e.set_thumbnail(url=target.display_avatar.url)
        
        top_list = []
        if stats:
            max_count = stats[0]['count']
            for i, row in enumerate(stats, 1):
                word = row['word']
                count = row['count']
                # Calculate bar length (max 15 chars)
                bar_len = min(int((count / max_count) * 15), 15)
                bar = "█" * bar_len + "░" * (15 - bar_len)
                
                # Format: 1. word [||||] 5
                top_list.append(f"`{i:2d}.` **{word:<12}** `{bar}` **{count}**")
        
        e.add_field(name="🏆 Топ слов", value="\n".join(top_list), inline=False)
        e.set_footer(text=f"Показаны топ {len(stats)} {declension(len(stats), 'слова', 'слов', 'слов')}")
        
        await ctx.send(embed=e)

async def setup(bot):
    await bot.add_cog(GeneralCommands(bot))