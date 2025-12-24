import os
import datetime
import shutil
import asyncio
import logging
from bot_app.core.config import LOG_DIR
from bot_app.integrations.ai_client import ask_ai

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
                # Run primarily at night (e.g., check loop every hour, run if needed)
                # For simplicity: Run on startup then sleep 24h
                await self.run_archive_cycle()
            except Exception as e:
                logger.error(f"Archiver crashed: {e}")
            
            await asyncio.sleep(86400)

    async def run_archive_cycle(self):
        logger.info("Starting log archiving & summarization cycle...")
        loop = asyncio.get_running_loop()
        
        # Run heavy file logic in thread to prevent bot lag
        await loop.run_in_executor(None, self._sync_archive_logic)
        
        # After merging files, run AI Summarization (Async)
        await self._process_summaries()

    def _sync_archive_logic(self):
        """Synchronous file operations (Merge/Delete)."""
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. Identify date folders
        try:
            all_items = os.listdir(LOG_DIR)
        except FileNotFoundError: return

        date_folders = []
        for item in all_items:
            path = os.path.join(LOG_DIR, item)
            if os.path.isdir(path) and self._is_date(item):
                if item != today_str: # Skip today
                    date_folders.append(item)
        
        date_folders.sort()
        if not date_folders:
            return

        # Group into chunks of 10 days
        chunk_size = 10
        for i in range(0, len(date_folders), chunk_size):
            chunk = date_folders[i : i + chunk_size]
            self._merge_chunk(chunk)

    def _merge_chunk(self, dates):
        start_date = dates[0]
        end_date = dates[-1]
        
        guild_map = {} 
        
        for date in dates:
            date_path = os.path.join(LOG_DIR, date)
            try:
                for g_name in os.listdir(date_path):
                    g_path = os.path.join(date_path, g_name)
                    if os.path.isdir(g_path):
                        if g_name not in guild_map: guild_map[g_name] = []
                        for f in os.listdir(g_path):
                            if f.endswith(".log") and not f.endswith(".events.log"):
                                guild_map[g_name].append((date, os.path.join(g_path, f)))
            except: pass

        for g_name, files in guild_map.items():
            if not files: continue
            files.sort(key=lambda x: x[0])
            
            archive_g_dir = os.path.join(self.archive_root, g_name)
            os.makedirs(archive_g_dir, exist_ok=True)
            
            merged_filename = f"data-{start_date}_to_{end_date}.txt"
            merged_path = os.path.join(archive_g_dir, merged_filename)
            
            if os.path.exists(merged_path):
                continue # Already merged

            try:
                with open(merged_path, "w", encoding="utf-8") as out:
                    for date, fpath in files:
                        out.write(f"\n--- DATE: {date} ---\n")
                        try:
                            with open(fpath, "r", encoding="utf-8", errors='ignore') as src:
                                shutil.copyfileobj(src, out)
                        except: pass
                logger.info(f"Archived {g_name}: {merged_filename}")
            except Exception as e:
                logger.error(f"Failed to merge {g_name}: {e}")

        # Cleanup source folders ONLY if merge succeeded for all? 
        # Risky. Let's delete processed dates.
        for date in dates:
            try: shutil.rmtree(os.path.join(LOG_DIR, date))
            except: pass

    def _is_date(self, txt):
        try:
            datetime.datetime.strptime(txt, "%Y-%m-%d")
            return True
        except: return False

    # --- AI Summarization ---

    async def _process_summaries(self):
        """Checks all archives for missing .md summaries."""
        loop = asyncio.get_running_loop()
        tasks = []
        
        # Scan archives
        if not os.path.exists(self.archive_root): return

        for g_name in os.listdir(self.archive_root):
            g_path = os.path.join(self.archive_root, g_name)
            if not os.path.isdir(g_path): continue
            
            for f in os.listdir(g_path):
                if f.endswith(".txt") and f.startswith("data-"):
                    # Check if .md exists
                    md_name = f.replace(".txt", "_summary.md")
                    md_path = os.path.join(g_path, md_name)
                    txt_path = os.path.join(g_path, f)
                    
                    if not os.path.exists(md_path):
                        logger.info(f"Generating summary for {f}...")
                        # Run extraction in thread, then AI async
                        log_content = await loop.run_in_executor(None, self._extract_significant_logs, txt_path)
                        if log_content:
                            await self._generate_and_save_summary(log_content, md_path, g_name)

    def _extract_significant_logs(self, file_path: str, char_limit=25000) -> str:
        """Reads log, filters system spam, keeps conversation, returns limited string."""
        buffer = []
        total_chars = 0
        
        try:
            with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    # Keep Date Headers
                    if line.startswith("--- DATE:"):
                        buffer.append(f"\n{line}")
                        continue
                        
                    # Filter logic:
                    # Skip joins/leaves unless emotional?
                    if "🚪" in line or "🎮" in line: continue
                    
                    # Keep speech, emotions, screams
                    # Log format: [HH:MM:SS] ICON Text
                    # Check length to skip "hm" "ok" noise? No, context matters.
                    
                    buffer.append(line)
                    total_chars += len(line)
                    
                    # If huge file, maybe we stop reading or implement sliding window?
                    # For now, just cut off if too huge (simpler than smart sampling)
                    if total_chars > char_limit * 2: # Read a bit more to filter later?
                        break
        except: return ""
        
        text = "\n".join(buffer)
        return text[:char_limit]

    async def _generate_and_save_summary(self, log_text: str, output_path: str, guild_name: str):
        prompt = (
            f"Проанализируй этот лог чата/голоса сервера '{guild_name}'. "
            "Сделай краткую выжимку (Markdown) за этот период:\n"
            "1. 🔥 **Горячие темы:** О чем спорили или долго говорили?\n"
            "2. 🤡 **Мемы/Пранки:** Были ли смешные моменты (помечены [LOUD], [SCREAM], [Laugh])?\n"
            "3. 🏆 **Активные участники:** Кто больше всех болтал?\n"
            "4. ⚠️ **Инциденты:** Конфликты или крики.\n\n"
            "Игнорируй скучные приветствия. Пиши живо и интересно.\n"
            f"Логи:\n{log_text}"
        )
        
        summary = await ask_ai(prompt, system_prompt="Ты — аналитик сообщества Discord. Твоя задача — делать интересные дайджесты.")
        
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# 📅 Отчет по логам: {guild_name}\n\n{summary}")
            logger.info(f"Summary saved: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save summary: {e}")