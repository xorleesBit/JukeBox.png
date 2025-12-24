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

    def get_user_logs(self, target_user, limit: int = 200, days_lookback: int = 5) -> str:
        """
        Retrieves last 'limit' lines associated with 'target_user' from logs.
        Scans today and previous 'days_lookback'.
        target_user can be Member object or string (legacy).
        Returns formatted text block.
        """
        lines_found = []
        
        # Determine search variations
        search_terms = set()
        if hasattr(target_user, 'name'):
            # It's a Discord Member/User
            search_terms.add(target_user.name.lower())
            search_terms.add(target_user.display_name.lower())
            if hasattr(target_user, 'global_name') and target_user.global_name:
                search_terms.add(target_user.global_name.lower())
        else:
            # It's a string
            search_terms.add(str(target_user).lower())
            
        # Helper check
        def matches(text):
            t_lower = text.lower()
            for term in search_terms:
                # Check "Term: message" format
                if t_lower.startswith(term + ":"):
                    return True, term
                # Check inclusion for system events
                if term in t_lower:
                    return True, None
            return False, None
        
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
                        
                        is_match, matched_term = matches(text)
                        
                        if is_match:
                            ts = float(data.get("ts", 0))
                            fmt_time = format_abs_ts(ts)
                            
                            if matched_term and text.lower().startswith(matched_term + ":"):
                                # Extracted speech
                                clean_text = text[len(matched_term)+1:].strip()
                                lines_found.append(f"[{date_str} {fmt_time}] {clean_text}")
                            else:
                                # System event or mention
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
                            content = f.readlines()
                            for line in reversed(content):
                                is_match, _ = matches(line)
                                if is_match and ":" in line:
                                    lines_found.append(line.strip())
                                    if len(lines_found) >= limit: break
                    except: continue

        # Reverse back to chronological order
        lines_found.reverse()
        return "\n".join(lines_found)
