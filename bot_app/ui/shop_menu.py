"""Shop menu UI wrapper - imports from shop.py cog"""
from bot_app.cogs.shop import ShopView as _ShopView
import discord

class ShopView(_ShopView):
    """Shop view adapted for control panel"""
    def __init__(self, db, guild_id):
        # Create minimal bot-like object for compatibility
        class BotProxy:
            def __init__(self, db_instance):
                self.db = db_instance
        
        bot_proxy = BotProxy(db)
        # Note: user_id will be set from interaction
        # For now we'll use a placeholder, it gets overridden in interaction_check
        super().__init__(bot_proxy, 0)
        self.guild_id = guild_id
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Update user_id from actual interaction
        self.user_id = interaction.user.id
        return True
