import os
import datetime
import shutil
import asyncio
import logging
from bot_app.core.config import LOG_DIR

logger = logging.getLogger("LogArchiver")

class LogArchiver:
    def __init__(self, bot):
        self.bot = bot
        self.archive_root = os.path.join(LOG_DIR, "archives")
        os.makedirs(self.archive_root, exist_ok=True)

    async def start(self):
        """Runs the archiving process daily."""
        while not self.bot.is_closed():
            try:
                await self.run_archive_cycle()
            except Exception as e:
                logger.error(f"Archiver crashed: {e}")
            
            # Wait 24h
            await asyncio.sleep(86400)

    async def run_archive_cycle(self):
        logger.info("Starting log archiving cycle...")
        
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. Identify date folders
        all_items = os.listdir(LOG_DIR)
        date_folders = []
        for item in all_items:
            path = os.path.join(LOG_DIR, item)
            if os.path.isdir(path) and self._is_date(item):
                if item != today_str: # Skip today
                    date_folders.append(item)
        
        date_folders.sort()
        if not date_folders:
            logger.info("No old logs to archive.")
            return

        # 2. Group by Guild inside those dates
        # Structure: LOG_DIR / DATE / GUILD_NAME_SANITIZED / ...
        # Problem: We need Guild ID to store in archives/GUILD_ID.
        # LogStore uses safe_dirname(guild_name). 
        # We might not know ID easily from folder name unless we map it back or check DB.
        # Solution: We will store archives by Guild NAME folder for now, or try to deduce ID.
        # Better: Since requirements said "command to get logs", likely by ID context. 
        # But folders are named by Name.
        # Let's stick to storing in archives/GUILD_NAME/ to be consistent with source.
        
        # We will process 10 days at a time
        chunk_size = 10
        for i in range(0, len(date_folders), chunk_size):
            chunk = date_folders[i : i + chunk_size]
            await self._process_chunk(chunk)

    def _is_date(self, txt):
        try:
            datetime.datetime.strptime(txt, "%Y-%m-%d")
            return True
        except: return False

    async def _process_chunk(self, dates):
        start_date = dates[0]
        end_date = dates[-1]
        
        # Collect all guild folders across these dates
        guild_map = {} # GuildName -> [list of (date, file_path)]
        
        for date in dates:
            date_path = os.path.join(LOG_DIR, date)
            for g_name in os.listdir(date_path):
                g_path = os.path.join(date_path, g_name)
                if os.path.isdir(g_path):
                    if g_name not in guild_map: guild_map[g_name] = []
                    
                    # Find log files
                    for f in os.listdir(g_path):
                        if f.endswith(".log") and not f.endswith(".events.log"): # legacy check
                            guild_map[g_name].append((date, os.path.join(g_path, f)))

        # Merge
        for g_name, files in guild_map.items():
            if not files: continue
            
            # Sort by date/time
            files.sort(key=lambda x: x[0]) 
            
            # Try to resolve Guild ID from DB? Too complex. Use Name.
            # But admin command uses Context (ID). 
            # We need a mapping. 
            # Let's iterate known guilds in bot cache to match name?
            # Or just save as Name and list dirs in Admin Command.
            # I will use safe name.
            
            archive_g_dir = os.path.join(self.archive_root, g_name) # Using Name not ID
            os.makedirs(archive_g_dir, exist_ok=True)
            
            merged_filename = f"data-{start_date}_to_{end_date}.txt"
            merged_path = os.path.join(archive_g_dir, merged_filename)
            
            try:
                with open(merged_path, "w", encoding="utf-8") as out:
                    for date, fpath in files:
                        out.write(f"\n--- DATE: {date} ---\\n")
                        try:
                            with open(fpath, "r", encoding="utf-8", errors='ignore') as src:
                                for line in src:
                                    # Add date if missing? Usually logs have [HH:MM:SS].
                                    # We prepend date header so it's readable.
                                    out.write(line)
                        except: pass
                
                logger.info(f"Archived {g_name}: {merged_filename}")
            except Exception as e:
                logger.error(f"Failed to merge {g_name}: {e}")

        # Cleanup source folders
        for date in dates:
            try:
                shutil.rmtree(os.path.join(LOG_DIR, date))
            except Exception as e:
                logger.error(f"Failed to delete {date}: {e}")
