import discord
from discord.ext import commands

# Colors
COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR = discord.Color.red()
COLOR_INFO = discord.Color.blue()
COLOR_WARNING = discord.Color.orange()

async def send_embed(ctx, title: str, description: str, color: discord.Color, ephemeral: bool = False, view: discord.ui.View = None, delete_after: int = None):
    """
    Universal helper to send unified embeds.
    Handles both Context (TextChannel) and Interaction.
    """
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    
    # If it's an interaction (Slash command context)
    if isinstance(ctx, discord.Interaction):
        # Interactions don't support delete_after directly in response, but do in followup/channel send
        # We generally prefer ephemeral for interactions if requested
        if ctx.response.is_done():
            await ctx.followup.send(embed=embed, ephemeral=ephemeral, view=view)
        else:
            await ctx.response.send_message(embed=embed, ephemeral=ephemeral, view=view)
    else:
        # Standard Context
        await ctx.send(embed=embed, view=view, delete_after=delete_after)

async def send_success(ctx, message: str, title: str = "Успешно", ephemeral: bool = False, delete_after: int = 10):
    await send_embed(ctx, f"✅ {title}", message, COLOR_SUCCESS, ephemeral, delete_after=delete_after)

async def send_error(ctx, error: str, title: str = "Ошибка", ephemeral: bool = True):
    await send_embed(ctx, f"❌ {title}", str(error), COLOR_ERROR, ephemeral, delete_after=20)

async def send_info(ctx, message: str, title: str = "Информация", ephemeral: bool = False):
    await send_embed(ctx, f"ℹ️ {title}", message, COLOR_INFO, ephemeral)

async def send_warning(ctx, message: str, title: str = "Внимание", ephemeral: bool = True):
    await send_embed(ctx, f"⚠️ {title}", message, COLOR_WARNING, ephemeral, delete_after=20)
