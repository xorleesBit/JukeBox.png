import time
import wave
import threading
import logging

try:
    import audioop
except ImportError:
    import audioop_lts as audioop

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2
BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH


class _UserState:
    __slots__ = ("buf", "silence_ms", "noise_ema", "kept_silence_ms", "started_ts", "last_ts")

    def __init__(self):
        self.buf = bytearray()
        self.silence_ms = 0.0
        self.noise_ema = 150.0
        self.kept_silence_ms = 0.0
        self.started_ts = 0.0
        self.last_ts = 0.0


class PrankSampler:
    """
    Always listens all users when capture enabled; splits into phrases by silence.
    Includes 'Gap Detection' to handle Discord/Krisp cutting off the stream entirely on silence.
    """
    def __init__(self, settings, on_phrase_ready_pcm):
        self.settings = settings
        self._lock = threading.Lock()
        self._states: dict[int, _UserState] = {}
        self._on_phrase_ready_pcm = on_phrase_ready_pcm 
        
        # Запускаем фоновый поток для проверки "потерянных" стримов (Watchdog)
        self._stop_event = threading.Event()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()
        
        logger.info("PrankSampler initialized.")

    def _state(self, user_id: int) -> _UserState:
        st = self._states.get(user_id)
        if st is None:
            st = _UserState()
            self._states[user_id] = st
        return st

    def _pcm_ms(self, pcm: bytes) -> float:
        return (len(pcm) / BYTES_PER_SEC) * 1000.0 if pcm else 0.0

    def _clip_ms(self, buf: bytearray) -> float:
        return (len(buf) / BYTES_PER_SEC) * 1000.0 if buf else 0.0

    def _flush_user_buffer(self, user_id: int, st: _UserState):
        """Helper to finalize and send the current buffer as a phrase."""
        if not st.buf:
            return
            
        created_ts = st.started_ts or time.time()
        clip_ms = self._clip_ms(st.buf)
        
        # Defaults if config is 0/missing
        clip_min_ms = self.settings.get_int("prank_clip_min_ms", 1000)
        clip_max_ms = self.settings.get_int("prank_clip_max_ms", 5000)

        # logger.debug(f"Checking phrase for {user_id}: len={clip_ms:.0f}ms (min={clip_min_ms}, max={clip_max_ms})")

        if clip_min_ms <= clip_ms <= clip_max_ms:
            logger.info(f"Phrase DETECTED for {user_id}! Length: {clip_ms:.0f}ms. Sending to Manager.")
            if callable(self._on_phrase_ready_pcm):
                try:
                    self._on_phrase_ready_pcm(int(user_id), float(created_ts), bytes(st.buf))
                except Exception as e:
                    logger.error(f"Error in on_phrase_ready_pcm callback: {e}")
        elif clip_ms > clip_max_ms:
             logger.info(f"Phrase discarded (too long): {clip_ms:.0f}ms")
        else:
             # Too short
             pass
        
        # Reset buffer state
        st.buf.clear()
        st.silence_ms = 0.0
        st.kept_silence_ms = 0.0
        st.started_ts = 0.0

    def feed(self, user_id: int | str, ts: float, pcm: bytes):
        if not pcm:
            return

        frame_ms = self._pcm_ms(pcm)
        if frame_ms <= 0:
            return

        try:
            rms = audioop.rms(pcm, 2)
        except Exception:
            return

        clip_max_ms = self.settings.get_int("prank_clip_max_ms", 5000)
        split_silence_ms = self.settings.get_int("prank_split_silence_ms", 1000)
        keep_silence_ms = self.settings.get_int("prank_keep_silence_ms", 200)
        rms_min = self.settings.get_int("prank_rms_min", 30)
        rms_mult = self.settings.get_float("prank_rms_mult", 1.2)

        try:
            uid_int = int(user_id)
        except (ValueError, TypeError):
            uid_int = 0

        with self._lock:
            st = self._state(uid_int)
            now = float(ts)

            # --- GAP DETECTION ---
            gap_threshold = (split_silence_ms / 1000.0) + 0.1
            if st.last_ts > 0 and (now - st.last_ts) > gap_threshold:
                # logger.debug(f"Gap detected for {uid_int}. Flushing.")
                self._flush_user_buffer(uid_int, st)
            
            st.last_ts = now

            # --- RMS LOGIC ---
            if rms < max(rms_min, st.noise_ema * 1.2):
                st.noise_ema = (0.98 * st.noise_ema) + (0.02 * float(rms))

            thr = max(rms_min, st.noise_ema * float(rms_mult))
            voiced = rms >= thr
            
            # Very verbose debug log (uncomment if desperate)
            # if voiced: logger.debug(f"Voiced packet: rms={rms} thr={thr}")

            if voiced:
                if not st.buf:
                    st.started_ts = now
                    # logger.debug(f"Voice started for {uid_int}")
                st.buf.extend(pcm)
                st.silence_ms = 0.0
                st.kept_silence_ms = 0.0
                
                # Safety limit check
                if self._clip_ms(st.buf) > (clip_max_ms + 1000):
                     self._flush_user_buffer(uid_int, st)
                return

            # Not voiced (silence packet received)
            if not st.buf:
                return

            st.silence_ms += frame_ms

            if st.kept_silence_ms < keep_silence_ms:
                st.buf.extend(pcm)
                st.kept_silence_ms += frame_ms

            if st.silence_ms >= split_silence_ms:
                # logger.debug(f"Silence split for {uid_int}")
                self._flush_user_buffer(uid_int, st)

    def _watchdog_loop(self):
        """Background loop to check for stalled buffers (when stream cuts off)."""
        logger.info("Sampler watchdog started.")
        while not self._stop_event.is_set():
            time.sleep(1.0) # Check every second
            self.check_timeouts()

    def check_timeouts(self):
        split_silence_ms = self.settings.get_int("prank_split_silence_ms", 600)
        # Allow a bit more margin for the watchdog
        timeout_sec = (split_silence_ms / 1000.0) + 0.2
        now = time.time()

        with self._lock:
            for uid, st in self._states.items():
                if st.buf and st.last_ts > 0:
                    if (now - st.last_ts) > timeout_sec:
                        # User stopped sending packets long ago
                        # logger.debug(f"Watchdog flushing {uid}")
                        self._flush_user_buffer(uid, st)

    def flush_all(self):
        logger.info("Flushing all sampler buffers.")
        self._stop_event.set()
        with self._lock:
            for user_id, st in self._states.items():
                self._flush_user_buffer(user_id, st)