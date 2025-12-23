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
from bot_app.core.log_store import LogStore
from bot_app.audio.vad import vad

logger = logging.getLogger(__name__)

@dataclass(order=True)
class ChunkJob:
    chunk_start: float
    chunk_end: float
    data: dict = field(compare=False)
    user_map: dict = field(compare=False)
    base_dir: str = field(compare=False)


class ChunkProcessor:
    """
    Sequential chunk processing; inside chunk transcribe per-user in parallel.
    Also can emit callback with phrase text for word stats.
    """
    def __init__(self, on_audio_phrase=None):
        self.q: queue.PriorityQueue[ChunkJob] = queue.PriorityQueue()
        self.stop_evt = threading.Event()
        self.thread: threading.Thread | None = None

        self.stats_lock = threading.Lock()
        self.total_text_bytes = 0
        self.last_audio_bytes = 0
        self.last_mp3_path: str | None = None

        self.on_after_chunk = None
        self.on_audio_phrase = on_audio_phrase  # callable(user_id:int, user_name:str, phrase_text:str)

        self._log_store_cache: dict[str, LogStore] = {}
        self._cache_lock = threading.Lock()
        
        # Pre-download VAD model
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
            if st:
                return st
            st = LogStore(base_dir)
            self._log_store_cache[base_dir] = st
            return st

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("ChunkProcessor thread started.")

    def stop(self):
        logger.info("ChunkProcessor stopping...")
        self.stop_evt.set()
        try:
            self.q.put_nowait(ChunkJob(time.time(), time.time(), {}, {}, base_dir=""))
        except Exception:
            pass

    def enqueue(self, job: ChunkJob):
        self.q.put(job)

    def queue_size(self) -> int:
        return self.q.qsize()

    def _recalc_total_text_bytes(self, base_dir: str) -> int:
        total = 0
        try:
            for fn in os.listdir(base_dir):
                if fn.endswith(".log") and len(fn) == len("HH.log"):
                    try:
                        total += os.path.getsize(os.path.join(base_dir, fn))
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def _loop(self):
        while not self.stop_evt.is_set():
            try:
                job = self.q.get(timeout=1.0)
            except queue.Empty:
                continue

            if self.stop_evt.is_set() and not job.data:
                self.q.task_done()
                break

            try:
                self._process(job)
            except Exception as e:
                logger.exception(f"Chunk processing error: {e}")
            finally:
                self.q.task_done()

    def _process(self, job: ChunkJob):
        logger.info(f"Processing chunk: {len(job.data)} users, duration={job.chunk_end - job.chunk_start:.1f}s")
        if not job.base_dir:
            # Should not happen unless dummy stop job
            return

        os.makedirs(job.base_dir, exist_ok=True)
        store = self._get_store(job.base_dir)

        if not job.data:
            return

        duration_sec = job.chunk_end - job.chunk_start
        duration_ms = max(0, int(duration_sec * 1000))
        full_mix = AudioSegment.silent(duration=duration_ms)

        temp_files = []
        futures = []
        fut_meta = {}

        def transcribe_one(wav_path: str, user_name: str):
            return transcribe_file_azure_sentences(wav_path, job.chunk_start, user_name, duration_sec)

        with ThreadPoolExecutor(max_workers=max(1, TRANSCRIBE_WORKERS)) as pool:
            for user_id, packets_or_buffer in job.data.items():
                user_name = job.user_map.get(user_id, f"User_{user_id}") if user_id != "Unknown" else "Unknown"

                # Handle DiskPacketBuffer
                if hasattr(packets_or_buffer, "read_all"):
                    try:
                        packets = packets_or_buffer.read_all()
                    except Exception as e:
                        logger.error(f"Failed to read packet buffer for {user_name}: {e}")
                        packets = []
                    finally:
                        try:
                            packets_or_buffer.close()
                        except Exception:
                            pass
                else:
                    packets = packets_or_buffer

                track = reconstruct_user_audio(packets, job.chunk_start, job.chunk_end)
                if len(track) > duration_ms:
                    track = track[:duration_ms]

                full_mix = full_mix.overlay(track)

                # VAD CHECK
                if not vad.validate(track):
                    # logger.info(f"VAD: Silence detected for {user_name}. Skipping STT.")
                    continue

                tmp = os.path.join(job.base_dir, f"_tmp_{int(job.chunk_start)}_{user_id}.wav")
                try:
                    track.export(tmp, format="wav")
                    temp_files.append(tmp)

                    fut = pool.submit(transcribe_one, tmp, user_name)
                    futures.append(fut)
                    fut_meta[fut] = (user_id, user_name)
                except Exception as e:
                    logger.error(f"Failed to export/submit audio for {user_name}: {e}")

            for fut in as_completed(futures):
                user_id, user_name = fut_meta.get(fut, ("Unknown", "Unknown"))
                try:
                    sentences = fut.result()  # list[(abs_ts, "User: text")]
                    # if sentences:
                    #    logger.info(f"Got {len(sentences)} sentences for {user_name}")
                    for abs_ts, line in sentences:
                        store.append_event(abs_ts, "🗣️", line)

                        # callback for word stats
                        phrase = line
                        prefix = f"{user_name}: "
                        if phrase.startswith(prefix):
                            phrase = phrase[len(prefix):].strip()
                        if callable(self.on_audio_phrase) and user_id != "Unknown":
                            try:
                                self.on_audio_phrase(int(user_id), user_name, phrase)
                            except Exception:
                                pass
                except Exception as e:
                    logger.error(f"Transcribe error for {user_name}: {e}")
                    continue

        gc.collect()
        for tmp in temp_files:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

        mp3_path = os.path.join(job.base_dir, "last_mix.mp3")
        try:
            full_mix.export(mp3_path, format="mp3")
            audio_size = os.path.getsize(mp3_path)
        except Exception:
            audio_size = 0

        store.ensure_rebuilt(job.chunk_start)
        store.ensure_rebuilt(job.chunk_end)

        with self.stats_lock:
            self.last_mp3_path = mp3_path
            self.last_audio_bytes = audio_size
            self.total_text_bytes = self._recalc_total_text_bytes(job.base_dir)

        if callable(self.on_after_chunk):
            try:
                self.on_after_chunk()
            except Exception:
                pass
