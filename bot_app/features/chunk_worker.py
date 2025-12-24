import os
import gc
import time
import queue
import threading
import logging
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydub import AudioSegment

from bot_app.core.config import TRANSCRIBE_WORKERS
from bot_app.audio.audio_utils import reconstruct_user_audio
from bot_app.integrations.azure_stt import transcribe_file_azure_sentences
from bot_app.integrations.assembly_stt import transcribe_file_assembly_sentences
from bot_app.core.log_store import LogStore
from bot_app.audio.vad import vad

logger = logging.getLogger(__name__)

@dataclass(order=True)
class ChunkJob:
    priority: int # 0=Emergency, 10=Normal (Lower processed first)
    chunk_start: float
    chunk_end: float
    data: dict = field(compare=False)
    user_map: dict = field(compare=False)
    base_dir: str = field(compare=False)
    guild_id: int = field(compare=False)
    stt_provider: str = field(compare=False, default="azure") # Added provider choice

class ChunkProcessor:
    def __init__(self, on_audio_phrase=None, db=None):
        self.q: queue.PriorityQueue[ChunkJob] = queue.PriorityQueue()
        self.stop_evt = threading.Event()
        self.thread: threading.Thread | None = None
        self.db = db # Injected

        self.stats_lock = threading.Lock()
        self.total_text_bytes = 0
        self.last_audio_bytes = 0
        self.last_mp3_path: str | None = None

        self.on_after_chunk = None
        self.on_audio_phrase = on_audio_phrase

        self._log_store_cache: dict[str, LogStore] = {}
        self._cache_lock = threading.Lock()
        
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(vad._ensure_model())
        except Exception: 
            pass
        
        logger.info("ChunkProcessor initialized.")

    def _get_store(self, base_dir: str) -> LogStore:
        with self._cache_lock:
            st = self._log_store_cache.get(base_dir)
            if st: return st
            st = LogStore(base_dir)
            self._log_store_cache[base_dir] = st
            return st

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("ChunkProcessor thread started.")

    def stop(self):
        logger.info("ChunkProcessor stopping...")
        self.stop_evt.set()
        try:
            # High priority poison pill
            self.q.put_nowait(ChunkJob(99, time.time(), time.time(), {}, {}, "", 0))
        except Exception: pass

    def join(self):
        """Waits for the worker thread to finish."""
        if self.thread and self.thread.is_alive():
            logger.info("Waiting for ChunkProcessor thread to finish...")
            self.thread.join()
            logger.info("ChunkProcessor thread finished.")

    def enqueue(self, job: ChunkJob):
        self.q.put(job)

    def queue_size(self) -> int:
        return self.q.qsize()

    def _recalc_total_text_bytes(self, base_dir: str) -> int:
        total = 0
        try:
            for fn in os.listdir(base_dir):
                if fn.endswith(".log") and len(fn) == len("HH.log"):
                    try: total += os.path.getsize(os.path.join(base_dir, fn))
                    except: pass
        except: pass
        return total

    def _loop(self):
        while not self.stop_evt.is_set():
            try: job = self.q.get(timeout=1.0)
            except queue.Empty: continue

            if self.stop_evt.is_set() and not job.data:
                self.q.task_done()
                break

            try: self._process(job)
            except Exception as e: logger.exception(f"Chunk processing error: {e}")
            finally: self.q.task_done()

    def _process(self, job: ChunkJob):
        logger.info(f"Processing chunk: {len(job.data)} users, duration={job.chunk_end - job.chunk_start:.1f}s")
        if not job.base_dir: return

        os.makedirs(job.base_dir, exist_ok=True)
        store = self._get_store(job.base_dir)

        if not job.data: return

        # --- SMART TRIM LOGIC ---
        # 1. Read all buffers first to find bounds
        loaded_data = {}
        global_min_ts = float('inf')
        global_max_ts = float('-inf')
        has_any_audio = False

        for user_id, packets_or_buffer in job.data.items():
            # Read buffer
            packets = []
            if hasattr(packets_or_buffer, "read_all"):
                try: packets = packets_or_buffer.read_all()
                except Exception as e:
                    logger.error(f"Failed to read buffer: {e}")
                finally:
                    try: packets_or_buffer.close()
                    except: pass
            else:
                packets = packets_or_buffer
            
            if packets:
                loaded_data[user_id] = packets
                # Check bounds
                # packets is list of (ts, pcm)
                # Sort just in case
                # packets.sort(key=lambda x: x[0]) # usually sorted
                p_start = packets[0][0]
                p_end = packets[-1][0]
                # Better precision: p_end + duration of last packet? 
                # Packet duration ~20ms, negligible.
                
                if p_start < global_min_ts: global_min_ts = p_start
                if p_end > global_max_ts: global_max_ts = p_end
                has_any_audio = True

        # 2. Check if empty
        if not has_any_audio or global_max_ts <= global_min_ts:
            logger.info("Chunk is empty (silence). Skipping MP3 generation.")
            # We still might want text logs? Proceed with empty audio logic?
            # User request: "only upload if not empty".
            # If we skip MP3, we just skip the audio gen part.
            pass
        else:
            # 3. Calculate Trimmed Bounds (with 2s buffer)
            # Ensure we don't go outside job bounds too much (though AudioSegment handles it)
            trim_start = max(job.chunk_start, global_min_ts - 2.0)
            trim_end = min(job.chunk_end, global_max_ts + 2.0)
            
            trimmed_duration = trim_end - trim_start
            
            if trimmed_duration < 1.0:
                logger.info("Audio too short (<1s). Skipping.")
            else:
                # Generate Audio
                duration_ms = int(trimmed_duration * 1000)
                full_mix = AudioSegment.silent(duration=duration_ms)
                
                temp_files = []
                futures = []
                fut_meta = {}
                
                speech_stats = {} # uid -> seconds

                def transcribe_one(wav_path: str, user_name: str):
                    if job.stt_provider == "assembly":
                        return transcribe_file_assembly_sentences(wav_path, trim_start, user_name, trimmed_duration)
                    else:
                        return transcribe_file_azure_sentences(wav_path, trim_start, user_name, trimmed_duration)

                with ThreadPoolExecutor(max_workers=max(1, TRANSCRIBE_WORKERS)) as pool:
                    for user_id, packets in loaded_data.items():
                        user_name = job.user_map.get(user_id, f"User_{user_id}") if user_id != "Unknown" else "Unknown"

                        # Reconstruct using TRIMMED bounds
                        track = reconstruct_user_audio(packets, trim_start, trim_end)
                        # Safety crop
                        if len(track) > duration_ms: track = track[:duration_ms]

                        full_mix = full_mix.overlay(track)

                        # VAD & Emotion Check
                        db = track.dBFS
                        emotion_tag = ""
                        if db > -5.0: emotion_tag = "[SCREAM] 😱"
                        elif db > -10.0: emotion_tag = "[LOUD] 🔊"
                        
                        if vad.validate(track):
                            non_silent_ms = len(packets) * 20
                            speech_stats[user_id] = non_silent_ms / 1000.0
                            
                            if emotion_tag:
                                store.append_event(trim_start, "🔥", f"{user_name} {emotion_tag}")

                            tmp = os.path.join(job.base_dir, f"_tmp_{int(trim_start)}_{user_id}.wav")
                            try:
                                # Padding for Azure STT stability
                                pad = AudioSegment.silent(duration=500)
                                track_padded = pad + track + pad
                                
                                # OPTIMIZATION: Convert to 16kHz Mono for Azure STT
                                # Azure prefers 16k mono. Sending 48k stereo might cause issues or extra cost.
                                track_export = track_padded.set_frame_rate(16000).set_channels(1)
                                
                                track_export.export(tmp, format="wav")
                                temp_files.append(tmp)

                                # Adjusted start time logic remains same (timestamps might slightly drift due to resampling but negligible)
                                
                                fut = pool.submit(transcribe_one, tmp, user_name)
                                futures.append(fut)
                                fut_meta[fut] = (user_id, user_name)
                            except Exception as e:
                                logger.error(f"Export/Submit error {user_name}: {e}")

                    for fut in as_completed(futures):
                        user_id, user_name = fut_meta.get(fut, ("Unknown", "Unknown"))
                        try:
                            sentences = fut.result()
                            for abs_ts, line in sentences:
                                store.append_event(abs_ts, "🗣️", line)
                                phrase = line
                                prefix = f"{user_name}: "
                                if phrase.startswith(prefix): phrase = phrase[len(prefix):].strip()
                                
                                if callable(self.on_audio_phrase) and user_id != "Unknown":
                                    try: self.on_audio_phrase(int(user_id), user_name, phrase)
                                    except: pass
                        except Exception as e:
                            logger.error(f"Transcribe error {user_name}: {e}")
                            continue

                # Finalize
                self.last_chunk_stats = (job.guild_id, speech_stats)

                gc.collect()
                for tmp in temp_files:
                    try:
                        if os.path.exists(tmp): os.remove(tmp)
                    except: pass

                mp3_path = os.path.join(job.base_dir, "last_mix.mp3")
                try:
                    full_mix.export(mp3_path, format="mp3")
                    self.last_audio_bytes = os.path.getsize(mp3_path)
                    self.last_mp3_path = mp3_path
                except: 
                    self.last_audio_bytes = 0
                    self.last_mp3_path = None

        # Text stats update
        store.ensure_rebuilt(job.chunk_start)
        store.ensure_rebuilt(job.chunk_end)

        with self.stats_lock:
            self.total_text_bytes = self._recalc_total_text_bytes(job.base_dir)

        if callable(self.on_after_chunk):
            try: self.on_after_chunk(self.last_chunk_stats)
            except: self.on_after_chunk()
        
        logger.info(f"Chunk done. QSize: {self.q.qsize()}")