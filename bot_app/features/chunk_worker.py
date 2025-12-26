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

@dataclass(order=True, slots=True)
class ChunkJob:
    priority: int # 0=Emergency, 10=Normal (Lower processed first)
    chunk_start: float
    chunk_end: float
    data: dict = field(compare=False)
    user_map: dict = field(compare=False)
    base_dir: str = field(compare=False)
    guild_id: int = field(compare=False)
    stt_provider: str = field(compare=False, default="azure")

class ChunkProcessor:
    def __init__(self, on_audio_phrase=None, db=None):
        self.q: queue.PriorityQueue[ChunkJob] = queue.PriorityQueue()
        self.stop_evt = threading.Event()
        self.thread: threading.Thread | None = None
        self.db = db

        self.stats_lock = threading.Lock()
        self.total_text_bytes = 0
        self.last_audio_bytes = 0
        self.last_mp3_path: str | None = None

        self.on_after_chunk = None
        self.on_audio_phrase = on_audio_phrase

        # LogStore cache with LRU and TTL
        self._log_store_cache: dict[str, tuple[LogStore, float]] = {}
        self._cache_lock = threading.Lock()
        self._cache_max_size = 50
        self._cache_ttl = 3600  # 1 hour
        
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(vad._ensure_model())
        except Exception: 
            pass
        
        logger.info("ChunkProcessor initialized.")

    def _get_store(self, base_dir: str) -> LogStore:
        """Get LogStore with LRU cache and TTL."""
        now = time.time()
        
        with self._cache_lock:
            # Check if exists and not expired
            if base_dir in self._log_store_cache:
                st, cached_time = self._log_store_cache[base_dir]
                
                # Check TTL
                if now - cached_time < self._cache_ttl:
                    return st
                else:
                    # Expired, remove it
                    self._log_store_cache.pop(base_dir)
                    logger.debug(f"LogStore cache expired for {base_dir}")
            
            # Create new
            st = LogStore(base_dir)
            self._log_store_cache[base_dir] = (st, now)
            
            # Evict oldest if size exceeded (simple FIFO since we can't easily implement LRU in threading)
            if len(self._log_store_cache) > self._cache_max_size:
                # Remove oldest by timestamp
                oldest_key = min(self._log_store_cache.keys(), 
                               key=lambda k: self._log_store_cache[k][1])
                self._log_store_cache.pop(oldest_key)
                logger.debug(f"LogStore cache evicted oldest: {oldest_key}")
            
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
            self.q.put_nowait(ChunkJob(99, time.time(), time.time(), {}, {}, "", 0))
        except Exception: pass

    def join(self):
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
                packets.sort(key=lambda x: x[0])
                loaded_data[user_id] = packets
                p_start = packets[0][0]
                p_end = packets[-1][0]
                
                if p_start < global_min_ts: global_min_ts = p_start
                if p_end > global_max_ts: global_max_ts = p_end
                has_any_audio = True

        if not has_any_audio or global_max_ts <= global_min_ts:
            logger.info("Chunk is empty (silence). Skipping.")
            return

        # --- 2. Human Pipeline (Mixing) ---
        # Optimized with in-memory buffer for mixing? 
        # Actually AudioSegment writes to disk for export(mp3). That's fine for the final file.
        mix_duration_sec = global_max_ts - global_min_ts
        if mix_duration_sec < 0.1: mix_duration_sec = 0.1
        
        mix_duration_ms = int(mix_duration_sec * 1000)
        full_mix = AudioSegment.silent(duration=mix_duration_ms, frame_rate=48000)
        
        speech_stats = {} 

        for user_id, packets in loaded_data.items():
            track = reconstruct_user_audio(packets, global_min_ts, global_max_ts)
            if len(track) > mix_duration_ms:
                track = track[:mix_duration_ms]
            full_mix = full_mix.overlay(track)
            speech_stats[user_id] = len(packets) * 0.02

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

        # --- 3. Robot Pipeline (STT Batching) ---
        futures = []
        fut_meta = {}
        
        # Helper for transcription
        def transcribe_one(audio_bytes: io.BytesIO, abs_start: float, user_name: str, duration: float):
            # Optimizations:
            # 1. Reset pointer
            audio_bytes.seek(0)
            # 2. Set name attribute for libraries that inspect it
            audio_bytes.name = "audio.wav"

            if job.stt_provider == "assembly":
                # Pass BytesIO directly (Supported by updated integration)
                return transcribe_file_assembly_sentences(audio_bytes, abs_start, user_name, duration)
            else:
                # Azure: Requires file path usually. We create temp file here ONLY if needed.
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(audio_bytes.read())
                    tmp_path = tmp.name
                try:
                    return transcribe_file_azure_sentences(tmp_path, abs_start, user_name, duration)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

        with ThreadPoolExecutor(max_workers=max(1, TRANSCRIBE_WORKERS)) as pool:
            for user_id, packets in loaded_data.items():
                user_name = job.user_map.get(user_id, f"User_{user_id}") if user_id != "Unknown" else "Unknown"
                
                # 3.1 VAD / Clustering
                segments = get_speech_segments(packets, gap_threshold=1.5)
                valid_segments = [s for s in segments if (s['end'] - s['start']) >= 0.5]
                
                if not valid_segments:
                    continue
                    
                # 3.2 Batch Assembly
                combined_audio = AudioSegment.silent(duration=0) 
                time_map = [] 
                silence_pad = AudioSegment.silent(duration=1000)
                
                for seg in valid_segments:
                    seg_audio = reconstruct_user_audio(seg['packets'], seg['start'], seg['end'])
                    seg_audio = seg_audio.set_frame_rate(16000).set_channels(1)
                    
                    start_ms = len(combined_audio)
                    combined_audio += seg_audio
                    end_ms = len(combined_audio)
                    
                    time_map.append({
                        'start_sec': start_ms / 1000.0,
                        'end_sec': end_ms / 1000.0,
                        'real_ts': seg['start']
                    })
                    combined_audio += silence_pad
                
                # Export Combined to In-Memory Buffer
                buf = io.BytesIO()
                combined_audio.export(buf, format="wav")
                # Buffer is ready for use
                
                # 3.3 Submit Batch
                fut = pool.submit(transcribe_one, buf, 0.0, user_name, len(combined_audio)/1000.0)
                futures.append(fut)
                fut_meta[fut] = (user_id, user_name, time_map)

            # --- 4. Collect & Map Results ---
            for fut in as_completed(futures):
                user_id, user_name, time_map = fut_meta.get(fut, ("Unknown", "Unknown", []))
                try:
                    sentences = fut.result()
                    for rel_ts, line in sentences:
                        matched_real_ts = None
                        for tm in time_map:
                            if (tm['start_sec'] - 0.5) <= rel_ts <= (tm['end_sec'] + 0.5):
                                matched_real_ts = tm['real_ts']
                                break
                        
                        if matched_real_ts is not None:
                            phrase = line
                            prefix = f"{user_name}: "
                            if phrase.startswith(prefix): phrase = phrase[len(prefix):].strip()
                            
                            store.append_event(matched_real_ts, "🗣️", f"{user_name}: {phrase}")
                            
                            if callable(self.on_audio_phrase) and user_id != "Unknown":
                                try: self.on_audio_phrase(int(user_id), user_name, phrase)
                                except: pass
                except Exception as e:
                    logger.error(f"Transcribe batch error {user_name}: {e}")
                    continue

        store.ensure_rebuilt(job.chunk_start)
        store.ensure_rebuilt(job.chunk_end)

        with self.stats_lock:
            self.total_text_bytes = self._recalc_total_text_bytes(job.base_dir)

        if callable(self.on_after_chunk):
            try: self.on_after_chunk(self.last_chunk_stats)
            except: self.on_after_chunk()
        
        logger.info(f"Chunk done. QSize: {self.q.qsize()}")
