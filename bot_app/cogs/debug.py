import discord
from discord.ext import commands
from bot_app.core.dev_manager import dev_manager
from bot_app.ui.debug_menu import DebugView

class DebugCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        # Only real owner can use !debug command initally
        return await self.bot.is_owner(ctx.author) or ctx.author.id in dev_manager.OWNER_IDS

    @commands.command(name="debug", hidden=True)
    async def debug_cmd(self, ctx):
        # Add owner if not present (auto-detect first user)
        if ctx.author.id not in dev_manager.OWNER_IDS:
            dev_manager.OWNER_IDS.add(ctx.author.id)
            
        view = DebugView(self.bot, ctx.author.id)
        embed = await view.get_status_embed()
        
        try: await ctx.message.delete()
        except: pass
        
        await ctx.send(embed=embed, view=view, delete_after=120)

async def setup(bot):
    await bot.add_cog(DebugCog(bot))
