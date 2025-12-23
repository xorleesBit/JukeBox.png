import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
AI_API_KEY = os.getenv("AI_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "chutes-llama-3.3-70b") # Default or from env
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://chutes.ai/api/v1")

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SERVICE_REGION = os.getenv("AZURE_REGION", "eastus")
AZURE_LANGUAGE = os.getenv("AZURE_LANGUAGE", "ru-RU")

DEFAULT_CHUNK_DURATION = int(os.getenv("CHUNK_DURATION", "300"))
DEFAULT_PUBLISH_SECONDS = int(os.getenv("PUBLISH_SECONDS", "300"))
DEFAULT_PRESENCE_POLL_SECONDS = int(os.getenv("PRESENCE_POLL_SECONDS", "300"))

LOG_DIR = os.getenv("LOG_DIR", "voice_logs")
TRANSCRIBE_WORKERS = int(os.getenv("TRANSCRIBE_WORKERS", "4"))

import sys

PROJECT_DIR = os.getcwd()

if sys.platform == "win32":
    FFMPEG_DIR = os.path.join(PROJECT_DIR, "env", "Scripts")
    FFMPEG_EXE = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
else:
    FFMPEG_DIR = "" 
    FFMPEG_EXE = "ffmpeg"

OPUS_DLL_NAME = "libopus-0.x64.dll"

# One DB + one phrases folder for whole bot
BOT_DB_PATH = os.path.join(LOG_DIR, "_bot.sqlite3")
PHRASES_DIR = os.path.join(LOG_DIR, "_phrases")

WORDS_FLUSH_SECONDS = int(os.getenv("WORDS_FLUSH_SECONDS", "600"))  # 10 min
