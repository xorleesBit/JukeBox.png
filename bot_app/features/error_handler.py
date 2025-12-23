import os
import sys
import traceback
import datetime
import logging
from bot_app.core.config import PROJECT_DIR

LOGS_DIR = os.path.join(PROJECT_DIR, "logs", "errors")

def ensure_log_dir():
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR, exist_ok=True)

def log_error(exception: Exception, ctx_info: str = ""):
    ensure_log_dir()
    now = datetime.datetime.now()
    filename = now.strftime("%Y-%m-%d.log")
    filepath = os.path.join(LOGS_DIR, filename)
    
    tb_str = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    
    entry = f"[{now.strftime('%H:%M:%S')}] {ctx_info}\n{tb_str}\n{'-'*40}\n"
    
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print(f"CRITICAL: Failed to write to error log: {e}")
        traceback.print_exc()

def get_log_files():
    ensure_log_dir()
    return sorted([f for f in os.listdir(LOGS_DIR) if f.endswith(".log")], reverse=True)

def read_log_segment(filename: str, lines=50) -> str:
    path = os.path.join(LOGS_DIR, filename)
    if not os.path.exists(path):
        return "File not found."
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.readlines()
            return "".join(content[-lines:])
    except Exception as e:
        return f"Error reading file: {e}"
