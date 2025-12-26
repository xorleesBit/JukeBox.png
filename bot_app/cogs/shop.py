import discord
from discord.ext import commands
from bot_app.core.items_registry import ITEMS, get_item
from bot_app.features.buff_manager import BuffManager
from bot_app.core.utils import has_balance

class ShopView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        
        # Build Select
        options = []
        for i_id, item in ITEMS.items():
            options.append(discord.SelectOption(
                label=f"{item.name} - {item.price}💰",
                emoji=item.emoji,
                value=i_id,
                description=item.description[:100]
            ))
            
        select = discord.ui.Select(placeholder="Купить предмет...", options=options)
        select.callback = self.buy_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def buy_callback(self, interaction: discord.Interaction):
        item_id = interaction.data['values'][0]
        item = get_item(item_id)
        
        # Check Balance
        bal = await self.bot.db.get_balance(interaction.guild_id, self.user_id)
        if bal < item.price:
            return await interaction.response.send_message(f"❌ Не хватает монет! Нужно {item.price}, у вас {bal}.", ephemeral=True)
            
        # Buy
        await self.bot.db.update_balance(interaction.guild_id, self.user_id, -item.price)
        await self.bot.db.add_item(interaction.guild_id, self.user_id, item_id, 1)
        
        await interaction.response.send_message(f"✅ Вы купили {item.emoji} **{item.name}**!", ephemeral=True)

class InventoryView(discord.ui.View):
    def __init__(self, bot, user_id, inventory_rows):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        
        # Select to Use
        if inventory_rows:
            options = []
            for row in inventory_rows:
                item = get_item(row['item_id'])
                if item:
                    options.append(discord.SelectOption(
                        label=f"{item.name} (x{row['count']})",
                        emoji=item.emoji,
                        value=item.id
                    ))
            
            if options:
                select = discord.ui.Select(placeholder="Использовать предмет...", options=options)
                select.callback = self.use_callback
                self.add_item(select)

    async def use_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        item_id = interaction.data['values'][0]
        
        success, msg = await self.bot.buff_manager.use_item(interaction.guild_id, self.user_id, item_id)
        await interaction.response.send_message(msg, ephemeral=True)
        # We should refresh the view, but for simplicity just msg

class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.buff_manager = BuffManager(bot.db) # Inject Manager

    @commands.command(name="shop")
    async def cmd_shop(self, ctx):
        """Магазин артефактов."""
        embed = discord.Embed(title="🛒 Магазин Артефактов", color=discord.Color.gold())
        
        desc = ""
        for item in ITEMS.values():
            desc += f"{item.emoji} **{item.name}** — `{item.price}💰`\n_{item.description}_\n\n"
        
        embed.description = desc
        view = ShopView(self.bot, ctx.author.id)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="inventory", aliases=["inv", "bag"])
    async def cmd_inventory(self, ctx):
        """Ваш инвентарь и активные эффекты."""
        # 1. Inventory
        inv_rows = await self.bot.db.get_inventory(ctx.guild.id, ctx.author.id)
        
        # 2. Buffs
        buffs = await self.bot.db.get_active_buffs(ctx.guild.id, ctx.author.id)
        
        embed = discord.Embed(title=f"🎒 Инвентарь: {ctx.author.display_name}", color=discord.Color.blue())
        
        # Items Field
        if inv_rows:
            txt = ""
            for row in inv_rows:
                item = get_item(row['item_id'])
                if item:
                    txt += f"{item.emoji} **{item.name}**: x{row['count']}\n"
            embed.add_field(name="Предметы", value=txt, inline=False)
        else:
            embed.add_field(name="Предметы", value="Пусто...", inline=False)
            
        # Buffs Field
        if buffs:
            txt = ""
            import time
            # Optimization: Pre-calculate map
            buff_map = {i.buff_id: i for i in ITEMS.values() if i.buff_id}
            
            for b in buffs:
                bid = b['buff_id']
                item = buff_map.get(bid)
                
                name = item.name if item else bid
                emoji = item.emoji if item else "✨"
                
                txt += f"{emoji} **{name}**: <t:{int(b['expires_at'])}:R>\n"
            embed.add_field(name="Активные Эффекты", value=txt, inline=False)
        else:
            embed.add_field(name="Активные Эффекты", value="Нет активных баффов.", inline=False)
            
        view = InventoryView(self.bot, ctx.author.id, inv_rows)
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(ShopCog(bot))