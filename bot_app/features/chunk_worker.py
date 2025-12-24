import os
import gc
import time
import queue
import threading
import logging
import io
import tempfile
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydub import AudioSegment

from bot_app.core.config import TRANSCRIBE_WORKERS
from bot_app.audio.audio_utils import reconstruct_user_audio, get_speech_segments
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

        # --- 1. Load Data & Calculate Bounds ---
        loaded_data = {}
        global_min_ts = float('inf')
        global_max_ts = float('-inf')
        has_any_audio = False

        for user_id, packets_or_buffer in job.data.items():
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
                # Ensure sorted
                packets.sort(key=lambda x: x[0])
                loaded_data[user_id] = packets
                p_start = packets[0][0]
                p_end = packets[-1][0] # Approx
                
                if p_start < global_min_ts: global_min_ts = p_start
                if p_end > global_max_ts: global_max_ts = p_end
                has_any_audio = True

        if not has_any_audio or global_max_ts <= global_min_ts:
            logger.info("Chunk is empty (silence). Skipping.")
            return

        # --- 2. Human Pipeline (Mixing) ---
        # Canvas: global_min_ts to global_max_ts
        # Requirement: "Find global min/max... Create 'base track' of silence duration max-min."
        
        mix_duration_sec = global_max_ts - global_min_ts
        # Just in case of floating point weirdness
        if mix_duration_sec < 0.1: mix_duration_sec = 0.1
        
        mix_duration_ms = int(mix_duration_sec * 1000)
        full_mix = AudioSegment.silent(duration=mix_duration_ms)
        
        speech_stats = {} # uid -> seconds

        for user_id, packets in loaded_data.items():
            # Reconstruct relative to global_min_ts
            # reconstruct_user_audio uses (chunk_start) to calc delay.
            # So passing global_min_ts as chunk_start aligns everyone correctly to the canvas start.
            track = reconstruct_user_audio(packets, global_min_ts, global_max_ts)
            
            # Crop to exact duration if slightly over due to packet rounding
            if len(track) > mix_duration_ms:
                track = track[:mix_duration_ms]
                
            full_mix = full_mix.overlay(track)
            
            # Simple speech stats (sum of packet durations)
            speech_stats[user_id] = len(packets) * 0.02 # approx 20ms

        # Export Human Mix
        mp3_path = os.path.join(job.base_dir, "last_mix.mp3")
        try:
            full_mix.export(mp3_path, format="mp3")
            self.last_audio_bytes = os.path.getsize(mp3_path)
            self.last_mp3_path = mp3_path
        except Exception as e:
            logger.error(f"MP3 Export failed: {e}")
            self.last_audio_bytes = 0
            self.last_mp3_path = None
            
        self.last_chunk_stats = (job.guild_id, speech_stats)

        # --- 3. Robot Pipeline (STT) ---
        futures = []
        fut_meta = {}
        
        # Helper for transcription
        def transcribe_one(audio_bytes: io.BytesIO, abs_start: float, user_name: str, duration: float):
            # Write to temp file just for the API call (Adapter pattern)
            # We use delete=False to ensure it exists for the called function, then delete manual.
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes.getvalue())
                tmp_path = tmp.name
            
            try:
                if job.stt_provider == "assembly":
                    return transcribe_file_assembly_sentences(tmp_path, abs_start, user_name, duration)
                else:
                    return transcribe_file_azure_sentences(tmp_path, abs_start, user_name, duration)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        with ThreadPoolExecutor(max_workers=max(1, TRANSCRIBE_WORKERS)) as pool:
            for user_id, packets in loaded_data.items():
                user_name = job.user_map.get(user_id, f"User_{user_id}") if user_id != "Unknown" else "Unknown"
                
                # 3.1 VAD / Clustering
                segments = get_speech_segments(packets, gap_threshold=1.5)
                
                for seg in segments:
                    # 3.2 Filter noise
                    seg_duration = seg['end'] - seg['start']
                    if seg_duration < 0.5:
                        continue
                        
                    # 3.3 Prepare Audio
                    # We reconstruct JUST this segment.
                    # Start/End are exact packet bounds, so no extra padding at start (delay=0).
                    seg_audio = reconstruct_user_audio(seg['packets'], seg['start'], seg['end'])
                    
                    # Convert to 16kHz Mono
                    seg_audio = seg_audio.set_frame_rate(16000).set_channels(1)
                    
                    # Export to BytesIO
                    buf = io.BytesIO()
                    seg_audio.export(buf, format="wav")
                    buf.seek(0)
                    
                    # 3.4 Submit
                    fut = pool.submit(transcribe_one, buf, seg['start'], user_name, seg_duration)
                    futures.append(fut)
                    fut_meta[fut] = (user_id, user_name)

            # --- 4. Collect Results ---
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

        # Text stats update
        store.ensure_rebuilt(job.chunk_start)
        store.ensure_rebuilt(job.chunk_end)

        with self.stats_lock:
            self.total_text_bytes = self._recalc_total_text_bytes(job.base_dir)

        if callable(self.on_after_chunk):
            try: self.on_after_chunk(self.last_chunk_stats)
            except: self.on_after_chunk()
        
        logger.info(f"Chunk done. QSize: {self.q.qsize()}")
