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
        # 1. Check Owner
        if ctx.author.id not in dev_manager.OWNER_IDS:
            dev_manager.OWNER_IDS.add(ctx.author.id)

        # 2. Enforce DM
        if not isinstance(ctx.channel, discord.DMChannel):
            try: await ctx.message.delete()
            except: pass
            try:
                await ctx.author.send("🔒 **Debug Menu** доступно только в Личных Сообщениях.")
            except: pass
            return

        print(f"[DEBUG_CMD] Triggered in DM by {ctx.author.id}")
            
        try:
            view = DebugView(self.bot, ctx.author.id)
            embed = await view.get_status_embed()
            
            await ctx.send(embed=embed, view=view)
        except Exception as e:
            print(f"[DEBUG_CMD] CRITICAL ERROR: {e}")
            import traceback
            traceback.print_exc()

async def setup(bot):
    await bot.add_cog(DebugCog(bot))
