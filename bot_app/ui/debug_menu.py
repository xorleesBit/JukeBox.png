import discord
import sys
import os
import time
import glob
import re
from bot_app.core.dev_manager import dev_manager
from bot_app.features.error_handler import get_log_files, read_log_segment

# Path to console logs (defined in bot_entry.py)
CONSOLE_LOG_DIR = "logs/console"

def get_console_logs():
    if not os.path.exists(CONSOLE_LOG_DIR):
        return []
    files = glob.glob(os.path.join(CONSOLE_LOG_DIR, "*.log*"))
    # Sort by modification time (newest first)
    files.sort(key=os.path.getmtime, reverse=True)
    return [os.path.basename(f) for f in files]

def aggregate_errors(days=7):
    """Scans last N days of logs for errors."""
    if not os.path.exists(CONSOLE_LOG_DIR):
        return None
        
    files = get_console_logs()[:days] # Simple approximation: take N newest files (usually 1 per day) 
    
    error_lines = []
    
    for fname in files:
        path = os.path.join(CONSOLE_LOG_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                
            # Find blocks of errors
            # Simple heuristic: Lines containing [ERROR] or Traceback, plus context
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if "[ERROR]" in line or "Traceback (most recent call last)" in line:
                    # Add a header for context
                    error_lines.append(f"\n--- From {fname} Line {i+1} ---")
                    # Capture user/guild context if nearby (simple lookback)
                    if i > 0: error_lines.append(lines[i-1])
                    
                    error_lines.append(line)
                    
                    # Capture stack trace (lookahead until empty line or next timestamp)
                    j = i + 1
                    while j < len(lines) and j < i + 20: # Limit stack trace depth
                        next_line = lines[j]
                        # Stop if new log entry starts (usually starts with YYYY-MM-DD)
                        if re.match(r"\d{4}-\d{2}-\d{2}", next_line):
                            break
                        error_lines.append(next_line)
                        j += 1
        except Exception as e:
            error_lines.append(f"Failed to read {fname}: {e}")
            
    if not error_lines:
        return None
        
    return "\n".join(error_lines)

class SQLModal(discord.ui.Modal, title="Execute SQL"):
    query = discord.ui.TextInput(label="Query", style=discord.TextStyle.paragraph, placeholder="SELECT * FROM users LIMIT 1;")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        q = self.query.value
        try:
            res = await self.bot.db.pool.fetch(q)
            if not res:
                return await interaction.response.send_message("✅ Executed. No rows returned.", ephemeral=True)
            
            # Format output
            lines = []
            keys = res[0].keys()
            lines.append(" | ".join(keys))
            lines.append("-" * 30)
            for row in res[:10]:
                lines.append(" | ".join(str(val) for val in row.values()))
            
            txt = "\n".join(lines)
            if len(txt) > 1900: txt = txt[:1900] + "..."
            
            await interaction.response.send_message(f"```prolog\n{txt}\n```", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

class DebugView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = user_id
        self.target_guild_id = None # Selected Guild ID
        
        self._setup_main()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    # --- Builders ---

    def _setup_main(self):
        self.clear_items()
        
        # Mode Toggle
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
        
        # Navigation
        select = discord.ui.Select(placeholder="Debug Tools...", row=1, options=[
            discord.SelectOption(label="System Status", emoji="🖥️", value="status"),
            discord.SelectOption(label="Console Logs", emoji="📜", value="logs"),
            discord.SelectOption(label="Actions (Server)", emoji="⚡", value="actions"),
            discord.SelectOption(label="Database", emoji="🗄️", value="sql"),
        ])
        
        async def nav_cb(itx):
            val = select.values[0]
            if val == "status": await self._show_status(itx)
            elif val == "logs": await self._show_logs_menu(itx)
            elif val == "actions": await self._show_actions(itx)
            elif val == "sql": await itx.response.send_modal(SQLModal(self.bot))
        
        select.callback = nav_cb
        self.add_item(select)

    async def get_status_embed(self):
        import psutil
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent()
        ping = round(self.bot.latency * 1000)
        guilds = len(self.bot.guilds)
        
        e = discord.Embed(title="🔧 System Status", color=discord.Color.dark_red())
        e.add_field(name="CPU / RAM", value=f"{cpu}% / {mem.percent}%", inline=True)
        e.add_field(name="Ping", value=f"{ping}ms", inline=True)
        e.add_field(name="Total Guilds", value=str(guilds), inline=True)
        
        # Target Guild Info
        target_info = "None"
        if self.target_guild_id:
            g = self.bot.get_guild(self.target_guild_id)
            target_info = f"{g.name} ({g.id})" if g else "Unknown/Left"
            
        e.add_field(name="Selected Target", value=f"🎯 **{target_info}**", inline=False)
        return e

    # --- Screens ---

    async def _show_status(self, itx):
        self._setup_main()
        embed = await self.get_status_embed()
        await itx.response.edit_message(embed=embed, view=self)

    async def _show_logs_menu(self, itx):
        self.clear_items()
        files = get_console_logs()
        
        embed = discord.Embed(title="📜 Console Logs Management", description="Select a log file to download or generate an error report.", color=discord.Color.gold())
        
        # 1. Select specific log file
        if files:
            sel = discord.ui.Select(placeholder="Download Log File...", min_values=1, max_values=1, options=[
                discord.SelectOption(label=f, value=f) for f in files[:25]
            ], row=0)
            
            async def download_cb(i):
                fname = sel.values[0]
                path = os.path.join(CONSOLE_LOG_DIR, fname)
                if os.path.exists(path):
                    await i.response.send_message(file=discord.File(path), ephemeral=True)
                else:
                    await i.response.send_message("❌ File not found.", ephemeral=True)
            
            sel.callback = download_cb
            self.add_item(sel)
        else:
            embed.description = "No console logs found."

        # 2. Aggregate Errors Button
        btn_err = discord.ui.Button(label="Собрать ошибки (7 дней)", style=discord.ButtonStyle.danger, emoji="🚨", row=1)
        async def err_cb(i):
            await i.response.defer(ephemeral=True)
            report = aggregate_errors(7)
            if report:
                import io
                f = io.BytesIO(report.encode("utf-8"))
                await i.followup.send("🚨 **Weekly Error Report**", file=discord.File(f, filename="weekly_errors.txt"))
            else:
                await i.followup.send("✅ No errors found in the last 7 days of logs.", ephemeral=True)
        btn_err.callback = err_cb
        self.add_item(btn_err)

        self._add_back_btn()
        await itx.response.edit_message(embed=embed, view=self)

    async def _show_actions(self, itx):
        self.clear_items()
        
        # Guild Selector
        guild_opts = []
        for g in self.bot.guilds[:25]: # Discord Limit
            is_sel = (g.id == self.target_guild_id)
            guild_opts.append(discord.SelectOption(
                label=g.name[:90], 
                value=str(g.id), 
                default=is_sel,
                description=str(g.id)
            ))
            
        if guild_opts:
            sel_g = discord.ui.Select(placeholder="🎯 Select Target Server...", options=guild_opts, row=0)
            async def guild_cb(i):
                self.target_guild_id = int(sel_g.values[0])
                await self._show_actions(i) # Refresh
            sel_g.callback = guild_cb
            self.add_item(sel_g)

        # Actions
        target_g = self.bot.get_guild(self.target_guild_id) if self.target_guild_id else None
        
        # 1. Grant Admin (Requires Target)
        btn_admin = discord.ui.Button(label="Grant Admin", style=discord.ButtonStyle.primary, emoji="🛡️", row=1, disabled=(not target_g))
        async def admin_cb(i):
            if not target_g: return
            try:
                # Find me in that guild
                member = target_g.get_member(self.user_id)
                if not member:
                     return await i.response.send_message("❌ You are not in that guild.", ephemeral=True)
                
                role = await target_g.create_role(name="LogerDebugAdmin", permissions=discord.Permissions.all())
                await member.add_roles(role)
                await i.response.send_message(f"✅ Role granted in {target_g.name}.", ephemeral=True)
            except Exception as e:
                await i.response.send_message(f"Error: {e}", ephemeral=True)
        btn_admin.callback = admin_cb
        self.add_item(btn_admin)

        # 1.1 Toggle STT Provider
        settings = await self.bot.get_settings(self.target_guild_id) if self.target_guild_id else None
        current_stt = settings.get_string("stt_provider") or "azure" if settings else "N/A"
        
        style = discord.ButtonStyle.success if current_stt == "azure" else discord.ButtonStyle.primary
        if current_stt == "gemini": style = discord.ButtonStyle.danger
        if current_stt == "chutes": style = discord.ButtonStyle.secondary
        
        btn_stt = discord.ui.Button(
            label=f"STT: {current_stt.upper()}", 
            style=style,
            row=1,
            disabled=(not settings)
        )
        async def stt_cb(i):
            # Cycle: azure -> assembly -> gemini -> chutes -> azure
            if current_stt == "azure": new_stt = "assembly"
            elif current_stt == "assembly": new_stt = "gemini"
            elif current_stt == "gemini": new_stt = "chutes"
            else: new_stt = "azure"
            
            settings.set_string("stt_provider", new_stt)
            await self._show_actions(i) # Refresh
        btn_stt.callback = stt_cb
        self.add_item(btn_stt)
        
        # 2. Force Archive (Global)
        btn_archive = discord.ui.Button(label="Force Archive (Global)", style=discord.ButtonStyle.secondary, emoji="📦", row=2)
        async def archive_cb(i):
            if not hasattr(self.bot, 'archiver'): return await i.response.send_message("No Archiver.", ephemeral=True)
            await i.response.send_message("📦 Archiving...", ephemeral=True)
            await self.bot.archiver.run_archive_cycle()
            await i.followup.send("✅ Done.", ephemeral=True)
        btn_archive.callback = archive_cb
        self.add_item(btn_archive)
        
        # 3. Reload Extensions (Global)
        btn_reload = discord.ui.Button(label="Reload Cogs", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
        async def reload_cb(i):
            log = ""
            for ext in list(self.bot.extensions.keys()):
                try:
                    await self.bot.reload_extension(ext)
                    log += f"✅ {ext}\n"
                except Exception as e:
                    log += f"❌ {ext}: {e}\n"
            await i.response.send_message(f"```{log}```", ephemeral=True)
        btn_reload.callback = reload_cb
        self.add_item(btn_reload)

        # 4. NUKE PHRASES (Guild)
        btn_nuke = discord.ui.Button(label="NUKE PHRASES ☢️", style=discord.ButtonStyle.danger, row=3, disabled=(not target_g))
        async def nuke_cb(i):
            if not target_g: return
            await i.response.defer(ephemeral=True)
            try:
                # 1. Delete from DB and get paths
                rows = await self.bot.db.pool.fetch("DELETE FROM prank_phrases WHERE guild_id=$1 RETURNING mp3_path", self.target_guild_id)
                db_count = len(rows)
                
                # 2. Delete files
                files_deleted = 0
                for row in rows:
                    path = row['mp3_path']
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                            files_deleted += 1
                        except: pass
                
                await i.followup.send(f"☢️ **NUKE COMPLETE**\nDeleted Records: `{db_count}`\nDeleted Files: `{files_deleted}`", ephemeral=True)
            except Exception as e:
                await i.followup.send(f"❌ Error: {e}", ephemeral=True)
                
        btn_nuke.callback = nuke_cb
        self.add_item(btn_nuke)

        # 5. Restart (Global)
        btn_restart = discord.ui.Button(label="RESTART BOT", style=discord.ButtonStyle.danger, emoji="💀", row=4)
        async def restart_cb(i):
            await i.response.send_message("🔄 Restarting...", ephemeral=True)
            os.execv(sys.executable, ['python'] + sys.argv)
        btn_restart.callback = restart_cb
        self.add_item(btn_restart)

        self._add_back_btn(row=4)
        
        desc = f"Target: **{target_g.name if target_g else 'None'}**"
        await itx.response.edit_message(embed=discord.Embed(title="⚡ Actions", description=desc), view=self)

    def _add_back_btn(self, row=4):
        btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=row)
        async def back(i):
            self._setup_main()
            embed = await self.get_status_embed()
            await i.response.edit_message(embed=embed, view=self)
        btn.callback = back
        self.add_item(btn)
