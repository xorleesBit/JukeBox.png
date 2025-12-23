import os
import time
import asyncio
import random
import re
import queue
import threading
import gc
import logging
import tempfile

import discord
from pydub import AudioSegment

from bot_app.core.config import PHRASES_DIR, FFMPEG_EXE
from bot_app.audio.audio_quality import pcm_to_mp3_pydub, mp3_to_wav_for_azure
from bot_app.audio.audio_utils import apply_effect

logger = logging.getLogger(__name__)

def safe_remove(path: str, tries: int = 5, delay: float = 0.5):
    if not path or not os.path.exists(path):
        return
    for _ in range(max(1, tries)):
        try:
            os.remove(path)
            return
        except PermissionError:
            gc.collect()
            time.sleep(delay)
        except Exception:
            return


class PrankManager:
    def __init__(self, bot: discord.Client, db, settings, guild_id: int, voice_logger):
        self.bot = bot
        self.db = db
        self.settings = settings
        self.guild_id = int(guild_id)
        self.logger = voice_logger

        self.guild_phrases_dir = os.path.join(PHRASES_DIR, str(guild_id))
        os.makedirs(self.guild_phrases_dir, exist_ok=True)

        self._writer_q: queue.Queue = queue.Queue(maxsize=2000)
        self._writer_task: asyncio.Task | None = None
        self._play_task: asyncio.Task | None = None
        
        logger.info(f"PrankManager initialized for guild {guild_id}")

    def capture_enabled(self) -> bool:
        return self.settings.get_bool("prank_capture_enabled")

    def play_enabled(self) -> bool:
        return self.settings.get_bool("prank_play_enabled")

    def should_accept_pcm(self) -> bool:
        return self.capture_enabled() and (not self.logger.is_prank_playing)

    def on_phrase_pcm(self, user_id: int | str, created_ts: float, pcm_bytes: bytes):
        if not self.capture_enabled():
            return
        try:
            self._writer_q.put_nowait((user_id, float(created_ts), pcm_bytes))
        except queue.Full:
            logger.warning("Writer queue full! Dropping phrase.")
            pass

    async def _writer_loop_async(self):
        logger.info("Writer loop started.")
        while True:
            try:
                try:
                    item = self._writer_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.5)
                    continue
                
                user_id, created_ts, pcm_bytes = item
                
                final_uid = 0
                try:
                    final_uid = int(user_id)
                except:
                    final_uid = 0 

                if await self.db.is_user_opt_out(self.guild_id, final_uid):
                    logger.info(f"User {final_uid} is opted out. Skipping.")
                    continue

                # Rotation Logic
                max_per_user = self.settings.get_int("prank_phrases_per_user")
                rotation_cooldown = self.settings.get_int("prank_rotation_cooldown_s", 300) # Default 5 min

                if max_per_user > 0:
                    stats = await self.db.get_user_phrase_stats(self.guild_id, final_uid)
                    count = stats['cnt'] or 0
                    newest = stats['newest'] or 0.0
                    
                    if count >= max_per_user:
                        # Check cooldown
                        if (time.time() - newest) < rotation_cooldown:
                            # Skipping write (cooldown active)
                            continue
                        
                        # Try to make space (Rotation)
                        deleted_paths = await self.db.enforce_phrase_limit(self.guild_id, final_uid, max_per_user - 1)
                        if not deleted_paths and count >= max_per_user:
                            # Could not delete anything (all favorites?) -> Skip
                            continue
                        
                        for path in deleted_paths:
                            safe_remove(path)

                logger.info(f"Processing phrase for user {final_uid} (len={len(pcm_bytes)} bytes)")

                phrase_id = await self.db.create_phrase_row(
                    self.guild_id, final_uid, created_ts, ""
                )

                mp3_name = f"{final_uid}_{phrase_id}_ready.mp3"
                mp3_path = os.path.join(self.guild_phrases_dir, mp3_name)

                ok = await asyncio.to_thread(
                    pcm_to_mp3_pydub,
                    pcm_bytes,
                    mp3_path,
                    frame_rate=48000,
                    channels=2,
                    sample_width=2,
                    bitrate="192k"
                )

                if not ok:
                    logger.error(f"Failed to encode phrase {phrase_id}")
                    await self.db.delete_phrase(phrase_id)
                    safe_remove(mp3_path)
                    continue

                await self.db.update_phrase_path(phrase_id, mp3_path)
                await self.db.mark_phrase_ready(phrase_id)
                logger.info(f"Phrase {phrase_id} saved.")

            except Exception as e:
                logger.exception(f"Writer error: {e}")

    def start_background(self):
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(self._writer_loop_async())
        if self._play_task is None or self._play_task.done():
            self._play_task = asyncio.create_task(self._play_loop())

    async def _play_loop(self):
        logger.info("Play loop started.")
        while True:
            await asyncio.sleep(1.0)

            if not self.play_enabled():
                continue

            vc = self.logger.vc
            if not vc or not vc.is_connected():
                continue

            # 1. Determine interval window
            interval_min = self.settings.get_int("prank_interval_minutes") or 2
            if interval_min < 1: interval_min = 1
            interval_sec = interval_min * 60

            now = time.time()
            # Calculate next slot start
            current_slot_start = (now // interval_sec) * interval_sec
            next_slot_start = current_slot_start + interval_sec
            
            # 2. Pick random time within that next slot
            # Ensure we don't pick a time that's passed if we are slightly late, 
            # but usually we aim for the future.
            offset = random.randint(0, interval_sec - 5) # Buffer 5 sec
            target_ts = next_slot_start + offset
            
            wait_time = target_ts - time.time()
            if wait_time > 0:
                logger.info(f"Next prank scheduled in {wait_time:.1f}s (Interval: {interval_min}m)")
                await asyncio.sleep(wait_time)
            
            # Re-check enabled state after sleep
            if not self.play_enabled():
                continue
            
            if not vc.is_connected():
                continue

            # 3. Wait for silence (Max Concurrent Speakers)
            max_speakers = self.settings.get_int("prank_max_concurrent_speakers") or 1
            
            # We poll until speaker count is low enough
            # Timeout 60s to avoid stuck loop if it's a very noisy channel, 
            # eventually we might just skip or force play. 
            # User instruction: "bot waits until they finish".
            # Let's wait up to `interval_sec` so we don't overlap next slot too much.
            
            wait_start = time.time()
            while True:
                if not vc.is_connected():
                    break
                    
                active_count = 0
                if self.logger.sink:
                    active_count = self.logger.sink.get_active_speaker_count(window_seconds=0.5)
                
                if active_count < max_speakers: # e.g. if max=2, we need 0 or 1 active
                    # Ready to play
                    await self.play_random()
                    break
                
                if (time.time() - wait_start) > (interval_sec * 0.8):
                    logger.info("Timed out waiting for silence. Skipping this slot.")
                    break
                
                await asyncio.sleep(1.0)

    async def play_random(self):
        # Retry logic: try up to 3 phrases to find one whose author is NOT speaking
        for _ in range(3):
            res = await self.db.random_ready_phrase(self.guild_id)
            if not res:
                return
            pid, path = res
            
            # Check speaker collision
            phrase_data = await self.db.get_phrase(pid)
            if phrase_data:
                author_id = phrase_data['user_id']
                
                # 1. Opt-out check
                if await self.db.is_user_opt_out(self.guild_id, author_id):
                    logger.info(f"Skipping phrase {pid}: user {author_id} is opted out.")
                    continue

                # 2. Speaking check
                if self.is_user_speaking(author_id):
                    logger.info(f"Skipping phrase {pid}: user {author_id} is speaking.")
                    continue 
            
            # Found good phrase
            logger.info(f"Playing random phrase: {pid}")
            await self.play_phrase_id(pid, record_play=True)
            return

    def is_user_speaking(self, user_id: int) -> bool:
        if not self.logger or not self.logger.sink:
            return False
        
        last_ts = self.logger.sink.active_speakers.get(user_id, 0)
        # If spoke in last 0.5s, consider active
        return (time.time() - last_ts) < 0.5

    async def play_phrase_id(self, phrase_id: int, record_play: bool, force_effect: str = None):
        vc = self.logger.vc
        if not vc or not vc.is_connected() or vc.is_playing():
            return

        phrase = await self.db.get_phrase(phrase_id)
        if not phrase:
            return

        # Opt-out safety check
        if await self.db.is_user_opt_out(self.guild_id, phrase['user_id']):
            return

        mp3_path = phrase["mp3_path"]
        if not mp3_path or not os.path.exists(mp3_path):
            return

        # Auto-Tune Logic
        play_path = mp3_path
        temp_file = None
        
        effect_to_apply = force_effect
        
        # If no forced effect, check auto-tune chance
        if not effect_to_apply and self.settings.get_bool("prank_auto_tune_enabled"):
            chance = self.settings.get_int("prank_auto_tune_chance") or 20
            if random.randint(1, 100) <= chance:
                effect_to_apply = random.choice(["helium", "demon", "reverb"])
                logger.info(f"Auto-Tune triggered! Applying {effect_to_apply}")

        if effect_to_apply:
            try:
                seg = AudioSegment.from_file(mp3_path)
                seg = apply_effect(seg, effect_to_apply)
                
                # Create temp file
                fd, temp_path = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)
                
                seg.export(temp_path, format="mp3")
                play_path = temp_path
                temp_file = temp_path
            except Exception as e:
                logger.error(f"Failed to apply effect {effect_to_apply}: {e}")
                play_path = mp3_path

        self.logger.is_prank_playing = True
        try:
            src = discord.FFmpegPCMAudio(
                executable=FFMPEG_EXE if os.path.exists(FFMPEG_EXE) else "ffmpeg",
                source=play_path,
            )
            vc.play(src)
            while vc.is_connected() and vc.is_playing():
                await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"Playback error: {e}")
        finally:
            self.logger.is_prank_playing = False
            if temp_file:
                safe_remove(temp_file)

        if record_play:
            await self.db.record_play(phrase_id)

    async def delete_phrase(self, phrase_id: int) -> bool:
        await self.db.delete_phrase(phrase_id)
        return True