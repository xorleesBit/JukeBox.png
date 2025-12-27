
import sys
import os

path = "voice_logs/2025-12-27/Galaktik team/2025-12-27.log"
try:
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        print(f"Total lines: {len(lines)}")
        for line in lines[-20:]: # Last 20 lines
            print(repr(line.strip()))
except Exception as e:
    print(f"Error: {e}")
