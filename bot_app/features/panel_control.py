import discord
import datetime
import asyncio
from bot_app.core.state import loggers, get_settings, AppWrapper
from bot_app.ui.control_panel import ControlPanelView, build_home_embed

async def pick_control_channel(guild: discord.Guild) -> discord.TextChannel | None:
    existing = discord.utils.get(guild.text_channels, name="loger-control")
    if existing and existing.permissions_for(guild.me).send_messages:
        return existing
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        return guild.system_channel
    for ch in guild.text_channels:
        perms = ch.permissions_for(guild.me)
        if perms.send_messages and perms.read_message_history and perms.embed_links:
            return ch
    return None

async def create_panel_in_channel(guild: discord.Guild, channel: discord.TextChannel, db) -> discord.Message | None:
    perms = channel.permissions_for(guild.me)
    if not (perms.send_messages and perms.embed_links and perms.read_message_history):
        return None

    view = ControlPanelView(AppWrapper(db), guild.id)
    settings = get_settings(guild.id)
    await settings.load()
    logger = loggers.get(guild.id)
    stats = await db.count_phrases(guild.id)
    embed = build_home_embed(guild, logger, settings, db, stats)

    # Clean legacy if sending new
    if channel.name == "loger-control":
        try: 
            await channel.purge(limit=10, check=lambda m: m.author == guild.me)
        except Exception: 
            pass

    msg = await channel.send(embed=embed, view=view)
    await db.set_panel(guild.id, channel.id, msg.id)
    # Note: We can't add view to bot here directly without passing 'bot' instance.
    # But usually 'msg = send(..., view=view)' attaches it for that interaction cycle.
    # For persistence, 'bot.add_view' is needed in on_ready or similar.
    return msg

async def ensure_panel_logic(bot: discord.Client, guild: discord.Guild, db, force_create_channel=False):
    channel = None
    if force_create_channel:
        existing = discord.utils.get(guild.text_channels, name="loger-control")
        if not existing:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                channel = await guild.create_text_channel("loger-control", overwrites=overwrites)
            except Exception: 
                pass
        else:
            channel = existing

    if not channel:
        channel = await pick_control_channel(guild)
    if not channel: 
        return

    panel_info = await db.get_panel(guild.id)
    panel_msg_id = panel_info[1] if panel_info else None

    # 1. Clean Channel (Delete all bot messages except the current panel ID)
    try:
        def is_me_trash(m):
            return m.author == bot.user and m.id != panel_msg_id
        await channel.purge(limit=50, check=is_me_trash)
    except Exception as e:
        print(f"Cleanup error in {guild.name}: {e}")

    # 2. Check / Restore Panel
    view = ControlPanelView(AppWrapper(db), guild.id)
    
    if panel_info:
        ch_id, msg_id = panel_info
        if ch_id == channel.id:
            try:
                msg = await channel.fetch_message(msg_id)
                
                # Check Age: if older than 2 days, recreate to keep it fresh at bottom
                age = datetime.datetime.now(datetime.timezone.utc) - msg.created_at
                if age.days > 2:
                    await msg.delete()
                    raise Exception("Panel too old, recreating")

                # Try to edit
                settings = get_settings(guild.id)
                await settings.load()
                logger = loggers.get(guild.id)
                stats = await db.count_phrases(guild.id)
                embed = build_home_embed(guild, logger, settings, db, stats)
                
                await msg.edit(embed=embed, view=view)
                bot.add_view(view)
                return
            except Exception as e:
                # print(f"Panel restore failed ({e}), creating new.")
                pass
    
    # 3. Create New
    msg = await create_panel_in_channel(guild, channel, db)
    if msg:
        bot.add_view(view)
