import os
import json
import datetime
from bot_app.core.config import LOG_DIR
from bot_app.core.utils import safe_dirname, format_abs_ts

class LogContext:
    def __init__(self, guild_id: int, guild_name: str):
        self.guild_dir_name = safe_dirname(guild_name)
        # However, VoiceLogger creates log structure: logs/DATE/GUILD_NAME/
        # We need to scan LOG_DIR/DATE/GUILD_NAME/YYYY-MM-DD.events.log
        self.base_dir = LOG_DIR

    def get_user_logs(self, user_name: str, limit: int = 200, days_lookback: int = 5) -> str:
        """
        Retrieves last 'limit' lines associated with 'user_name' from logs.
        Scans today and previous 'days_lookback'.
        Returns formatted text block.
        """
        lines_found = []
        user_name_lower = user_name.lower()
        
        # Scan dates in reverse
        now = datetime.datetime.now()
        dates_to_check = []
        for i in range(days_lookback + 1):
            d = now - datetime.timedelta(days=i)
            dates_to_check.append(d.strftime("%Y-%m-%d"))

        # Limit total lines processed to avoid lag
        processed_count = 0
        MAX_PROCESS = 10000 

        for date_str in dates_to_check:
            # Path: voice_logs/DATE/GUILD_NAME/DATE.events.log
            # Note: VoiceLogger logic for ensure_log_dir uses safe_dirname(guild.name)
            # We assume guild name hasn't changed dramatically.
            
            # Since we don't know exact guild folder name if it changed, 
            # we might need to search inside the date folder for the matching guild folder.
            # But let's assume standard path first.
            
            day_folder = os.path.join(self.base_dir, date_str, self.guild_dir_name)
            event_log = os.path.join(day_folder, f"{date_str}.events.log")
            
            if not os.path.exists(event_log):
                continue
            
            try:
                # Read backwards or full read?
                # Full read is safer for JSONL.
                with open(event_log, "r", encoding="utf-8") as f:
                    file_lines = f.readlines()
                    
                # Iterate in reverse to find newest first
                for line in reversed(file_lines):
                    if processed_count >= MAX_PROCESS: break
                    processed_count += 1
                    
                    try:
                        data = json.loads(line)
                        text = data.get("text", "")
                        
                        # Check if this log belongs to user.
                        # VoiceLogger format: "UserName: message" or "UserName joined."
                        # We want what they SAID mainly.
                        # STT format: "UserName: phrase"
                        
                        if text.lower().startswith(user_name_lower + ":"):
                            # Extracted speech/text
                            ts = float(data.get("ts", 0))
                            fmt_time = format_abs_ts(ts)
                            clean_text = text[len(user_name)+1:].strip() # remove "Name:"
                            lines_found.append(f"[{date_str} {fmt_time}] {clean_text}")
                            
                        elif user_name_lower in text.lower():
                            # Events like join/leave or mention
                            # Maybe exclude system events for better roast context?
                            # Let's include them but marked
                            # lines_found.append(f"[Event] {text}")
                            pass
                            
                    except: continue
                    
                    if len(lines_found) >= limit:
                        break
            except Exception:
                continue
                
            if len(lines_found) >= limit:
                break
        
        # 2. ALSO check archives
        if len(lines_found) < limit:
            archive_guild_dir = os.path.join(self.base_dir, "archives", self.guild_dir_name)
            if os.path.exists(archive_guild_dir):
                # Archives are named data-START_to_END.txt
                # We sort them to find newest archives first
                arch_files = sorted([f for f in os.listdir(archive_guild_dir) if f.endswith(".txt")], reverse=True)
                
                for arch_f in arch_files:
                    if len(lines_found) >= limit: break
                    
                    try:
                        with open(os.path.join(archive_guild_dir, arch_f), "r", encoding="utf-8", errors='ignore') as f:
                            # Archive files are plain text, not JSONL.
                            # Format: [HH:MM:SS] ICON User: Text
                            # But wait, LogArchiver prepends "--- DATE: ... ---"
                            # We need to parse this.
                            content = f.readlines()
                            for line in reversed(content):
                                if user_name_lower in line.lower() and ":" in line:
                                    # Very simple check for archive text
                                    lines_found.append(line.strip())
                                    if len(lines_found) >= limit: break
                    except: continue

        # Reverse back to chronological order
        lines_found.reverse()
        return "\n".join(lines_found)
