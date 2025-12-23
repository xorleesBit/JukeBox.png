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
        print(f"[DEBUG_CMD] Triggered by {ctx.author.id}. Owner IDs: {dev_manager.OWNER_IDS}")
        
        # Add owner if not present (auto-detect first user)
        if ctx.author.id not in dev_manager.OWNER_IDS:
            print(f"[DEBUG_CMD] User {ctx.author.id} is NOT in OWNER_IDS. Auto-adding...")
            dev_manager.OWNER_IDS.add(ctx.author.id)
            
        try:
            view = DebugView(self.bot, ctx.author.id)
            embed = await view.get_status_embed()
            
            # Try to delete user message
            try: await ctx.message.delete()
            except Exception as e: print(f"[DEBUG_CMD] Delete msg fail: {e}")
            
            await ctx.send(embed=embed, view=view, delete_after=120)
            print("[DEBUG_CMD] Menu sent successfully.")
        except Exception as e:
            print(f"[DEBUG_CMD] CRITICAL ERROR: {e}")
            import traceback
            traceback.print_exc()

async def setup(bot):
    await bot.add_cog(DebugCog(bot))
