"""Inventory menu UI wrapper - imports from shop.py cog"""
from bot_app.cogs.shop import InventoryView as _InventoryView
import discord

class InventoryView(discord.ui.View):
    """Inventory view adapted for control panel"""
    def __init__(self, db, guild_id, user_id):
        super().__init__(timeout=300)
        self.db = db
        self.guild_id = guild_id
        self.user_id = user_id
        self._setup_task = None
        
    async def on_timeout(self):
        """Cleanup on timeout"""
        pass
    
    async def _build_view(self, interaction: discord.Interaction):
        """Build the inventory view asynchronously"""
        # Get inventory
        inv_rows = await self.db.get_inventory(self.guild_id, self.user_id)
        
        # Get buffs
        buffs = await self.db.get_active_buffs(self.guild_id, self.user_id)
        
        embed = discord.Embed(
            title=f"🎒 Инвентарь: {interaction.user.display_name}",
            color=discord.Color.blue()
        )
        
        # Items
        if inv_rows:
            from bot_app.core.items_registry import get_item
            txt = ""
            for row in inv_rows:
                item = get_item(row['item_id'])
                if item:
                    txt += f"{item.emoji} **{item.name}**: x{row['count']}\n"
            embed.add_field(name="Предметы", value=txt or "Пусто...", inline=False)
        else:
            embed.add_field(name="Предметы", value="Пусто...", inline=False)
        
        # Active Buffs
        if buffs:
            from bot_app.core.items_registry import ITEMS
            txt = ""
            buff_map = {i.buff_id: i for i in ITEMS.values() if hasattr(i, 'buff_id') and i.buff_id}
            
            for b in buffs:
                bid = b['buff_id']
                item = buff_map.get(bid)
                name = item.name if item else bid
                emoji = item.emoji if item else "✨"
                txt += f"{emoji} **{name}**: <t:{int(b['expires_at'])}:R>\n"
            
            embed.add_field(name="Активные Эффекты", value=txt, inline=False)
        else:
            embed.add_field(name="Активные Эффекты", value="Нет активных баффов.", inline=False)
        
        return embed
    
    async def send_ephemeral(self, interaction: discord.Interaction):
        """Send inventory as ephemeral message"""
        embed = await self._build_view(interaction)
        self._add_use_menu(await self.db.get_inventory(self.guild_id, self.user_id))
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def start(self, interaction: discord.Interaction):
        """Start the inventory view (Edit mode)"""
        embed = await self._build_view(interaction)
        self._add_use_menu(await self.db.get_inventory(self.guild_id, self.user_id))
        await interaction.response.edit_message(embed=embed, view=self)

    def _add_use_menu(self, inv_rows):
        if inv_rows:
            from bot_app.core.items_registry import get_item
            options = []
            for row in inv_rows:
                item = get_item(row['item_id'])
                if item:
                    options.append(discord.SelectOption(
                        label=f"{item.name} (x{row['count']})",
                        emoji=item.emoji,
                        value=item.id
                    ))
            
            if options:
                # Remove old select if any? View is fresh usually.
                select = discord.ui.Select(placeholder="Использовать предмет...", options=options)
                select.callback = self.use_callback
                self.add_item(select)
    
    async def use_callback(self, interaction: discord.Interaction):
        """Use an item"""
        if interaction.user.id != self.user_id:
            return
        
        item_id = interaction.data['values'][0]
        
        # Use buff manager
        from bot_app.features.buff_manager import BuffManager
        buff_mgr = BuffManager(self.db)
        success, msg = await buff_mgr.use_item(self.guild_id, self.user_id, item_id)
        
        await interaction.response.send_message(msg, ephemeral=True)
