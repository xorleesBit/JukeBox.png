import sys
import os
import discord
import discord.opus
from pydub import AudioSegment
from .config import PROJECT_DIR, OPUS_DLL_NAME, FFMPEG_DIR, FFMPEG_EXE

def setup_audio_libraries():
    """
    Loads Opus library, patches discord.py decoder, and configures Pydub.
    """
    _load_opus()
    _patch_decoder()
    _setup_pydub()

def _load_opus():
    if sys.platform != "win32":
        if not discord.opus.is_loaded():
            try:
                discord.opus.load_opus("libopus.so.0")
            except Exception as e:
                print(f"⚠️ Failed to load libopus.so.0: {e}")
        return

    opus_path = os.path.join(PROJECT_DIR, OPUS_DLL_NAME)
    if not discord.opus.is_loaded():
        if os.path.exists(opus_path):
            try:
                discord.opus.load_opus(opus_path)
            except Exception as e:
                print(f"❌ Failed to load Opus DLL: {e}")
                sys.exit(1)
        else:
            print(f"❌ Opus DLL not found: {opus_path}")
            sys.exit(1)

def _patch_decoder():
    """
    Patches discord.opus.Decoder to avoid crashing on bad packets.
    """
    _original = discord.opus.Decoder.decode
    def patched(self, *args, **kwargs):
        try:
            return _original(self, *args, **kwargs)
        except Exception:
            # Return empty bytes on decode error to prevent crash
            return b""
    discord.opus.Decoder.decode = patched

def _setup_pydub():
    if sys.platform != "win32":
        AudioSegment.converter = "ffmpeg"
        AudioSegment.ffprobe = "ffprobe"
        return
    
    # Add FFMPEG to PATH if not present
    if "PATH" in os.environ and FFMPEG_DIR and (FFMPEG_DIR not in os.environ["PATH"]):
        os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ["PATH"]

    ffprobe = os.path.join(FFMPEG_DIR, "ffprobe.exe")
    if os.path.exists(FFMPEG_EXE):
        AudioSegment.converter = FFMPEG_EXE
    if os.path.exists(ffprobe):
        AudioSegment.ffprobe = ffprobe
