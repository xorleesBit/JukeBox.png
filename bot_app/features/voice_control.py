import discord
from bot_app.core.state import loggers, get_settings, AppWrapper
from bot_app.features.voice_logger import VoiceLogger
from bot_app.ui.control_panel import ControlPanelView

async def ensure_logger_started(interaction: discord.Interaction, db):
    g = interaction.guild
    if not g: 
        return
    
    member = interaction.user
    if not isinstance(member, discord.Member) or not member.voice:
        return await interaction.followup.send("Сначала зайдите в голосовой канал.", ephemeral=True)
    
    logger = loggers.get(g.id)
    if logger and logger.is_recording: 
        return

    settings = get_settings(g.id)
    # Pass 'bot' from interaction.client
    logger = VoiceLogger(interaction.client, guild_id=g.id, text_channel_id=interaction.channel.id, db=db, settings=settings)
    loggers[g.id] = logger
    
    # Link Dashboard (Persistence)
    panel_info = await db.get_panel(g.id)
    if panel_info:
        c_id, m_id = panel_info
        try:
            ch = g.get_channel(c_id)
            if ch:
                msg = await ch.fetch_message(m_id)
                logger.dashboard_message = msg
                # Re-create view with AppWrapper
                logger.view = ControlPanelView(AppWrapper(db), g.id)
        except Exception:
            pass

    await logger.start(guild=g, voice_channel=member.voice.channel, text_channel=interaction.channel)

async def ensure_logger_stopped(guild_id: int):
    l = loggers.get(guild_id)
    if l:
        await l.stop()
        loggers.pop(guild_id, None)
