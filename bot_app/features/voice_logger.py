import os
import time
import asyncio
import datetime
import re
import logging
import audioop

import discord
from discord.ext import voice_recv

from bot_app.core.config import DEFAULT_CHUNK_DURATION, DEFAULT_PUBLISH_SECONDS, LOG_DIR, WORDS_FLUSH_SECONDS
from bot_app.core.utils import safe_dirname, fmt_bytes, fmt_duration, get_msc_now
from bot_app.audio.sinks import TimeStampedSink
from .chunk_worker import ChunkProcessor, ChunkJob
from bot_app.ui.ui import ControlView
from bot_app.core.log_store import LogStore

from .words_accumulator import WordsAccumulator
from bot_app.audio.prank_sampler import PrankSampler
from .prank_manager import PrankManager

logger = logging.getLogger(__name__)

_word_re = re.compile(r"\b\w+\b", flags=re.UNICODE)


def count_words(text: str) -> int:
    return len(_word_re.findall(text or ""))


class VoiceLogger:
    def __init__(self, bot: discord.Client, guild_id: int, text_channel_id: int, db, settings):
        self.bot = bot
        self.guild_id = int(guild_id)
        self.text_channel_id = int(text_channel_id)

        self.db = db
        self.settings = settings

        self.voice_channel_id: int | None = None
        self.vc: voice_recv.VoiceRecvClient | None = None
        self.sink: TimeStampedSink | None = None

        self.is_recording = False
        self.is_paused = False
        self.state = "idle"

        self.chunk_duration = self.settings.get_int("logger_chunk_seconds") or DEFAULT_CHUNK_DURATION
        self.publish_interval = self.settings.get_int("logger_publish_seconds") or DEFAULT_PUBLISH_SECONDS
        
        # Auto-Pause
        self.auto_pause_minutes = self.settings.get_int("auto_pause_minutes") or 10
        self.last_voice_time = time.time()

        self.started_at = 0.0
        self.pause_started_at: float | None = None
        self.paused_total = 0.0

        self.dashboard_message: discord.Message | None = None
        self.upload_message: discord.Message | None = None
        self.view: ControlView | None = None

        self._timer_reset_evt = asyncio.Event()
        self._publish_reset_evt = asyncio.Event()

        self.base_dir: str | None = None
        self.log_store: LogStore | None = None

        self.words_acc = WordsAccumulator()
        self.words_task: asyncio.Task | None = None
        
        # Batch buffer for word updates (optimized)
        self.pending_updates: dict[int, dict] = {}  # user_id -> aggregated stats
        self.pending_lock = asyncio.Lock()
        self.max_pending_updates = 1000  # Limit to prevent memory issues

        self.is_prank_playing = False
        self.prank: PrankManager | None = None
        self.sampler: PrankSampler | None = None

        cm = getattr(self.bot, 'context_manager', None)
        self.processor = ChunkProcessor(
            on_audio_phrase=self._on_audio_phrase_from_worker_thread,
            context_manager=cm
        )
        
        # Safe callback wrapper for thread-to-async communication
        self.processor.on_after_chunk = self._safe_callback_wrapper(self._handle_chunk_complete)

        self.loop_task: asyncio.Task | None = None
        self.publish_task: asyncio.Task | None = None
        self.last_publish_at = 0.0
    
    def _safe_callback_wrapper(self, coro_func):
        """Safe wrapper for callbacks from worker threads."""
        def wrapper(*args, **kwargs):
            if self.bot.is_closed() or not self.bot.loop.is_running():
                logger.warning("Bot loop not running, skipping callback")
                return
            
            try:
                future = asyncio.run_coroutine_threadsafe(
                    coro_func(*args, **kwargs),
                    self.bot.loop
                )
                
                # Add error handler
                def handle_result(fut):
                    try:
                        fut.result()
                    except Exception as e:
                        logger.error(f"Callback error: {e}", exc_info=True)
                
                future.add_done_callback(handle_result)
            except Exception as e:
                logger.error(f"Failed to schedule callback: {e}")
        
        return wrapper

    async def set_chunk_duration(self, seconds: int):
        self.chunk_duration = seconds
        self.settings.set_int("logger_chunk_seconds", seconds)
        self._timer_reset_evt.set()

    async def set_publish_interval(self, seconds: int):
        self.publish_interval = seconds
        self.settings.set_int("logger_publish_seconds", seconds)
        self._publish_reset_evt.set()

    def _ensure_log_dir(self, guild_name: str):
        if self.base_dir:
            return
        day = datetime.datetime.now().strftime("%Y-%m-%d")
        self.base_dir = os.path.join(LOG_DIR, day, safe_dirname(guild_name))
        os.makedirs(self.base_dir, exist_ok=True)
        self.log_store = LogStore(self.base_dir, rebuild_debounce_sec=0.8, write_bom_for_human_log=True)

    def log_event(self, ts: float, icon: str, text: str):
        if self.log_store:
            # We ignore 'ts' (which is usually unix timestamp) for text formatting
            # and use current MSC time for the log line prefix
            now_msc = get_msc_now().timestamp()
            self.log_store.append_event(now_msc, icon, text)

    def log_chat_message(self, user: str, text: str):
        if self.log_store and self.is_recording and not self.is_paused:
            self.log_event(time.time(), "💬", f"{user}: {text}")

    def recorded_seconds(self) -> float:
        if not self.is_recording:
            return 0.0
        now = time.time()
        paused = self.paused_total
        if self.pause_started_at is not None:
            paused += (now - self.pause_started_at)
        return max(0.0, now - self.started_at - paused)

    # ---- Energy VAD & Auto-Pause Logic ----
    
    def _check_activity(self, pcm_data):
        """Called for every packet by Sink."""
        try:
            rms = audioop.rms(pcm_data, 2)
        except Exception: 
            return

        if rms > 300: # Threshold for activity
            self.last_voice_time = time.time()
            if self.is_paused and self.state == "listening":
                # Wake Up from auto-pause
                self.is_paused = False
                self.log_event(time.time(), "▶️", "Auto-Resume: Voice detected")
                self._timer_reset_evt.set() # Wake up chunk loop if sleeping
                
                # Force dashboard update
                try:
                    asyncio.run_coroutine_threadsafe(self.update_dashboard(), self.bot.loop)
                except Exception as e:
                    logger.debug(f"Dashboard update error on resume: {e}")

    # ---- words ----
    def _on_audio_phrase_from_worker_thread(self, user_id: int, user_name: str, phrase_text: str):
        if self.bot.is_closed() or not self.bot.loop.is_running():
            return

        if isinstance(user_id, int):
            try:
                asyncio.run_coroutine_threadsafe(
                    self._async_process_audio_words(user_id, user_name, phrase_text),
                    self.bot.loop
                )
            except Exception:
                pass

    async def _async_process_audio_words(self, user_id: int, user_name: str, phrase_text: str):
        if await self.db.is_user_opt_out(self.guild_id, user_id):
            return
        
        w_count = count_words(phrase_text)
        if w_count == 0:
            return
            
        # VAD FAILSAFE: If we transcribed words, there WAS voice activity
        self.last_voice_time = time.time()
        
        async with self.pending_lock:
            # Aggregate by user
            if user_id not in self.pending_updates:
                self.pending_updates[user_id] = {
                    'user_name': user_name,
                    'count': 0,
                    'words_sample': []  # Store only first 50 words as sample
                }
            
            stats = self.pending_updates[user_id]
            stats['count'] += w_count
            stats['user_name'] = user_name
            
            # Limit sample to 50 words
            words = phrase_text.split()
            if len(stats['words_sample']) < 50:
                stats['words_sample'].extend(words[:50 - len(stats['words_sample'])])
            
            # Force flush if batch too large
            total_pending = sum(s['count'] for s in self.pending_updates.values())
            if total_pending >= self.max_pending_updates:
                asyncio.create_task(self._flush_words_now())

    async def _flush_words_now(self):
        """Immediate flush of pending word updates."""
        async with self.pending_lock:
            if not self.pending_updates:
                return
            
            updates = self.pending_updates
            self.pending_updates = {}
        
        # Process batches
        for uid, stats in updates.items():
            try:
                await self.db.upsert_user(self.guild_id, uid, stats['user_name'])
                await self.db.add_xp_and_words(
                    self.guild_id,
                    uid,
                    stats['count'],
                    w_text=0,
                    w_audio=stats['count'],
                    words_list=stats['words_sample']  # Only sample
                )
            except Exception as e:
                logger.error(f"Flush error for {uid}: {e}")

    async def _words_flush_loop(self):
        """
        Periodically flushes accumulated word stats to DB (Batch Insert).
        """
        while self.is_recording:
            await asyncio.sleep(WORDS_FLUSH_SECONDS)
            
            # Use the same flush logic
            await self._flush_words_now()

    # ---- start/stop ----
    async def start(self, guild: discord.Guild, voice_channel: discord.VoiceChannel, text_channel: discord.TextChannel):
        self._ensure_log_dir(guild.name)

        self.is_recording = True
        self.is_paused = False
        self.state = "connecting"
        self.started_at = time.time()
        self.last_voice_time = time.time() # Reset voice time
        self.paused_total = 0.0
        self.pause_started_at = None
        self.voice_channel_id = int(voice_channel.id)
        self.text_channel_id = int(text_channel.id)
        self.last_publish_at = time.time()

        self.processor.start()
        
        logger.info(f"Connecting to voice channel {voice_channel.id} in guild {guild.id}")

        try:
            self.vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        except Exception as e:
            self.is_recording = False
            self.state = "error"
            logger.error(f"Failed to connect to voice: {e}")
            await text_channel.send(f"Err: {e}", delete_after=8)
            return

        self.prank = PrankManager(self.bot, db=self.db, settings=self.settings, guild_id=self.guild_id, voice_logger=self)
        self.prank.start_background()

        self.sampler = PrankSampler(settings=self.settings, on_phrase_ready_pcm=self.prank.on_phrase_pcm)

        ignore_ids = set()
        for member in voice_channel.members:
            if member.bot:
                ignore_ids.add(member.id)
        if self.bot.user:
            ignore_ids.add(self.bot.user.id)

        # Intercept PCM in Sink
        def on_pcm_wrapper(uid, ts, pcm):
            # Ignore packets from unknown users (SSRC mapping incomplete) to prevent noise
            if uid is None or uid == 0:
                return

            self._check_activity(pcm) # Energy check
            if self.sampler:
                self.sampler.feed(uid, ts, pcm)

        self.sink = TimeStampedSink(
            is_paused_callable=lambda: self.is_paused or self.is_prank_playing,
            ignore_user_ids=ignore_ids,
            on_pcm=on_pcm_wrapper,
            should_forward_pcm=(lambda: bool(self.prank and self.prank.should_accept_pcm())) if self.prank else None,
        )
        self.vc.listen(self.sink)
        logger.info("Voice connection established. Sink started listening.")

        self.state = "listening"
        self.words_task = asyncio.create_task(self._words_flush_loop())
        self.loop_task = asyncio.create_task(self._chunk_loop())
        self.publish_task = asyncio.create_task(self._publish_loop())

    async def stop(self):
        if not self.is_recording:
            return
        logger.info("Stopping logger...")
        self.state = "stopping"
        self.is_recording = False

        if self.words_task:
            self.words_task.cancel()

        if self.sampler:
            self.sampler.flush_all()

        if self.loop_task:
            self.loop_task.cancel()
        if self.publish_task:
            self.publish_task.cancel()

        if self.vc and self.sink:
            now = time.time()
            with self.sink.lock:
                data = self.sink.user_data
                start = self.sink.start_time
                self.sink.user_data = {}
                self.sink.start_time = now

            u_map = self._build_user_map(self.vc.channel.guild, data)
            await self._enqueue_chunk(data, start, now, u_map)

            try:
                self.vc.stop_listening()
            except Exception:
                pass
            try:
                await self.vc.disconnect()
            except Exception:
                pass

        self.processor.stop()
        self.state = "stopped"
        logger.info("Logger stopped.")

    # ---- chunk/publish ----
    async def _chunk_loop(self):
        while self.is_recording:
            # Auto-Pause Check
            if self.auto_pause_minutes > 0 and not self.is_paused:
                elapsed_silence = time.time() - self.last_voice_time
                if elapsed_silence > (self.auto_pause_minutes * 60):
                    logger.info("Auto-Pausing due to silence.")
                    self.log_event(time.time(), "⏸️", f"Auto-Pause: Silence > {self.auto_pause_minutes}m")
                    # Force rotate to save pending audio
                    await self.rotate()
                    self.is_paused = True
                    await self.update_dashboard()

            if self.is_paused or not self.sink:
                await asyncio.sleep(1) # Sleep while paused
                continue

            now = time.time()
            next_at = self.sink.start_time + self.chunk_duration
            timeout = max(0.2, next_at - now)

            try:
                await asyncio.wait_for(self._timer_reset_evt.wait(), timeout=timeout)
                self._timer_reset_evt.clear()
                continue
            except asyncio.TimeoutError:
                await self.rotate()

    async def rotate(self, priority=10):
        if not self.sink:
            return

        now = time.time()
        with self.sink.lock:
            data = self.sink.user_data
            start = self.sink.start_time
            self.sink.user_data = {}
            self.sink.start_time = now

        u_map = self._build_user_map(self.vc.channel.guild, data)
        
        # Read STT provider from settings (default to azure)
        provider = self.settings.get_string("stt_provider") or "azure"
        
        await self._enqueue_chunk(data, start, now, u_map, priority, provider)

    async def _enqueue_chunk(self, data, start, end, u_map, priority=10, provider="azure"):
        if not self.base_dir:
            return
        
        filtered_data = {}
        for uid, pcm in data.items():
            final_uid = uid
            if uid == "Unknown" or uid is None:
                final_uid = "Unknown_User"
            
            # Ignore self (Bot)
            if final_uid == self.bot.user.id:
                if hasattr(pcm, "close"): pcm.close()
                continue

            if isinstance(final_uid, int):
                if await self.db.is_user_opt_out(self.guild_id, final_uid):
                    if hasattr(pcm, "close"): pcm.close()
                    continue
                
                # BUFF CHECK: Ghost Mode
                if hasattr(self.bot, 'buff_manager'):
                    is_ghost = await self.bot.buff_manager.has_buff(self.guild_id, final_uid, "ghost_mode")
                    if is_ghost:
                        if hasattr(pcm, "close"): pcm.close()
                        continue
            
            filtered_data[final_uid] = pcm
        
        if not filtered_data:
            return

        job = ChunkJob(priority, chunk_start=start, chunk_end=end, data=filtered_data, user_map=u_map, base_dir=self.base_dir, guild_id=self.guild_id, stt_provider=provider)
        self.processor.enqueue(job)

    def _build_user_map(self, guild: discord.Guild, data: dict) -> dict[int | str, str]:
        u_map: dict[int | str, str] = {}
        for u in data.keys():
            if u == "Unknown" or u is None:
                u_map["Unknown_User"] = "Unknown User"
                continue
            if isinstance(u, int):
                m = guild.get_member(u)
                u_map[u] = m.name if m else f"User_{u}"
            else:
                u_map[u] = str(u)
        return u_map

    async def _handle_chunk_complete(self, stats=None):
        # Update Dashboard
        await self.update_dashboard()
        
        # Update Speech Stats in DB (if stats provided)
        if stats and isinstance(stats, tuple) and len(stats) == 2:
            gid, speech_map = stats
            if gid == self.guild_id and speech_map:
                for uid, secs in speech_map.items():
                    if isinstance(uid, int):
                        await self.db.update_speech_stats(gid, uid, secs)

    async def _publish_loop(self):
        self.last_publish_at = time.time()
        while self.is_recording:
            now = time.time()
            next_at = self.last_publish_at + self.publish_interval
            timeout = max(0.5, next_at - now)

            try:
                await asyncio.wait_for(self._publish_reset_evt.wait(), timeout=timeout)
                self._publish_reset_evt.clear()
                continue
            except asyncio.TimeoutError:
                await self.publish_now(force=False)

    async def publish_now(self, force=False, include_audio=False):
        if not self.base_dir:
            return
        self.last_publish_at = time.time()
        channel = self.bot.get_channel(self.text_channel_id)
        if not channel:
            return

        files_to_send = []
        
        # 1. MP3 file (Only if requested)
        if include_audio:
            mp3_path = os.path.join(self.base_dir, "last_mix.mp3")
            if os.path.exists(mp3_path):
                files_to_send.append(discord.File(mp3_path, filename=f"mix_{int(time.time())}.mp3"))

        # 2. Log file for current day
        if self.log_store:
            latest_day = self.log_store.latest_day_str()
            if latest_day:
                log_path = self.log_store.human_log_path(latest_day)
                if os.path.exists(log_path):
                     files_to_send.append(discord.File(log_path, filename=f"log_{latest_day}_{int(time.time())}.txt"))

        if not files_to_send:
            return

        try:
            msg = await channel.send(content=f"Авто-выгрузка логов [{datetime.datetime.now().strftime('%H:%M')}]", files=files_to_send)
            
            # Persistence: Update DB
            await self.db.set_last_log_msg(self.guild_id, channel.id, msg.id)
            
            # Legacy local tracking (optional, kept for compatibility if needed elsewhere)
            if self.upload_message:
                try:
                    await self.upload_message.delete()
                except:
                    pass
            self.upload_message = msg
        except Exception as e:
            print(f"Error publishing: {e}")

    async def play_sound(self, file_path: str):
        """
        Plays an arbitrary sound file to the voice channel if connected.
        Used by Soundpad.
        """
        if not self.vc or not self.vc.is_connected():
            return False
        
        if self.vc.is_playing():
            return False

        self.is_prank_playing = True # Block recording of this sound
        try:
            from bot_app.core.config import FFMPEG_EXE
            source = discord.FFmpegPCMAudio(executable=FFMPEG_EXE if os.path.exists(FFMPEG_EXE) else "ffmpeg", source=file_path)
            self.vc.play(source)
            while self.vc.is_connected() and self.vc.is_playing():
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Play sound error: {e}")
        finally:
            self.is_prank_playing = False
        return True

    def make_dashboard_embed(self) -> discord.Embed:
        e = discord.Embed(title="Voice Logger", color=discord.Color.blurple())
        
        # Enhanced status
        state_emoji = "🔴"
        if self.state == "listening":
            state_emoji = "🟢"
        elif self.state == "connecting":
            state_emoji = "🟡"
            
        status_val = f"{state_emoji} {self.state}"
        if self.is_paused:
            status_val += " (PAUSED 💤)"
            
        e.add_field(name="Status", value=status_val, inline=True)
        e.add_field(name="Recorded", value=fmt_duration(self.recorded_seconds()), inline=True)
        e.add_field(name="Chunk", value=f"{self.chunk_duration}s", inline=True)
        e.add_field(name="Upload", value=f"{self.publish_interval}s", inline=True)
        
        ap_text = f"{self.auto_pause_minutes}m" if self.auto_pause_minutes > 0 else "OFF"
        e.add_field(name="Auto-Pause", value=ap_text, inline=True)
        return e

    async def update_dashboard(self):
        if not self.dashboard_message:
            return
        try:
            await self.dashboard_message.edit(embed=self.make_dashboard_embed(), view=self.view)
        except Exception:
            pass