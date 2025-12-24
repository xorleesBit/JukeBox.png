import discord
import os
from bot_app.core.config import LOG_DIR
from bot_app.core.utils import safe_dirname

class ArchiveSelect(discord.ui.Select):
    def __init__(self, guild_id, archives):
        self.guild_id = guild_id
        options = []
        # Sort by name (date usually) desc
        archives.sort(reverse=True)
        
        for f in archives[:25]:
            # f is "data-2025-01-01_to_... .txt"
            lbl = f.replace("data-", "").replace(".txt", "")
            options.append(discord.SelectOption(label=lbl, value=f))
            
        super().__init__(placeholder="Выберите период...", options=options)

    async def callback(self, interaction: discord.Interaction):
        fname = self.values[0]
        # Locate file. We need Guild Name folder.
        # Problem: We only have ID. LogArchiver saves by Name.
        # We need to find the folder.
        
        archive_root = os.path.join(LOG_DIR, "archives")
        target_path = None
        target_md = None
        
        # Search for folder that matches guild name?
        # Better: Search inside all folders for this file? 
        # Filename contains dates, not unique enough if multiple guilds have same dates?
        # Wait, ControlPanelView knows Guild ID.
        # LogArchiver saves by NAME.
        # We should try to find the folder by Name.
        
        g = interaction.guild
        if not g: return
        
        g_dir = safe_dirname(g.name)
        # Try exact match first
        path = os.path.join(archive_root, g_dir, fname)
        if not os.path.exists(path):
            # Fallback: Search all folders? No, security risk.
            return await interaction.response.send_message("❌ Файл не найден (возможно имя сервера изменилось?).", ephemeral=True)
            
        files = [discord.File(path)]
        
        # Check summary
        md_name = fname.replace(".txt", "_summary.md")
        md_path = os.path.join(archive_root, g_dir, md_name)
        if os.path.exists(md_path):
            files.append(discord.File(md_path))
            
        await interaction.response.send_message(f"📦 **Архив:** {fname}", files=files, ephemeral=True)

class ArchiveView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self._init_ui()

    def _init_ui(self):
        # Scan dir
        # We need Guild Object to get Name. 
        # View is init with ID. We don't have Guild obj easily here unless passed or fetched.
        # Wait, interaction gives us Guild.
        # But we need to build Select BEFORE interaction.
        # So we can't fully build it in __init__ if we rely on Name for folder path.
        pass
        
        # Solution: Add a "Load" button or require Guild Name passed.
        # Let's assume we can't easily get Name in __init__ without async.
        # Hack: The button in ControlPanelView has 'self.app' but not guild obj?
        # Interaction in ControlPanelView has interaction.guild.
        
        # Let's fix ControlPanelView call first.
        
        self.add_item(discord.ui.Button(label="Загрузить список", style=discord.ButtonStyle.primary, custom_id="load_arch"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get('custom_id') == "load_arch":
            await self._load_list(interaction)
            return False # Stop propagation
        return True

    async def _load_list(self, interaction):
        g = interaction.guild
        if not g: return
        
        g_dir = safe_dirname(g.name)
        archive_root = os.path.join(LOG_DIR, "archives", g_dir)
        
        if not os.path.exists(archive_root):
            return await interaction.response.send_message("📂 Архив пуст.", ephemeral=True)
            
        files = [f for f in os.listdir(archive_root) if f.endswith(".txt") and f.startswith("data-")]
        if not files:
            return await interaction.response.send_message("📂 Архив пуст.", ephemeral=True)
            
        self.clear_items()
        self.add_item(ArchiveSelect(self.guild_id, files))
        await interaction.response.edit_message(view=self)
