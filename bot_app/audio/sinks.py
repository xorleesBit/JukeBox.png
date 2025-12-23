import time
import threading
import logging
from discord.ext import voice_recv
from bot_app.audio.packet_buffer import DiskPacketBuffer

logger = logging.getLogger(__name__)

class TimeStampedSink(voice_recv.AudioSink):
    def __init__(self, is_paused_callable, ignore_user_ids=None, on_pcm=None, should_forward_pcm=None):
        super().__init__()
        # user_data: dict[user_id, DiskPacketBuffer]
        self.user_data: dict[int | str, DiskPacketBuffer] = {}
        self.start_time = time.time()
        self.lock = threading.Lock()

        self._is_paused_callable = is_paused_callable
        self._ignore_user_ids = set(ignore_user_ids or [])

        self._on_pcm = on_pcm
        self._should_forward_pcm = should_forward_pcm
        
        self._packet_count = 0
        self.active_speakers: dict[int | str, float] = {}

    def wants_opus(self) -> bool:
        return False

    def get_active_speaker_count(self, window_seconds: float = 0.5) -> int:
        now = time.time()
        count = 0
        to_remove = []
        for uid, last_ts in self.active_speakers.items():
            if now - last_ts < window_seconds:
                count += 1
            elif now - last_ts > 60:
                to_remove.append(uid)
        for uid in to_remove:
            self.active_speakers.pop(uid, None)
        return count

    def write(self, user, data):
        if self._is_paused_callable():
            return
        if not data or not getattr(data, "pcm", None):
            return

        user_id = user.id if user else "Unknown"
        if user_id in self._ignore_user_ids:
            return

        now = time.time()
        pcm = data.pcm
        
        self.active_speakers[user_id] = now

        self._packet_count += 1
        if self._packet_count % 250 == 0:
            # Verbose log reduced to debug
            # logger.debug(f"Sink received 250 packets. Last from: {user_id}")
            pass

        with self.lock:
            # Use DiskPacketBuffer instead of list
            if user_id not in self.user_data:
                self.user_data[user_id] = DiskPacketBuffer()
            self.user_data[user_id].append(now, pcm)

        # Forward to PrankSampler (Real-time memory handling, separate from archive)
        if callable(self._on_pcm) and callable(self._should_forward_pcm):
            try:
                if self._should_forward_pcm():
                    final_uid = 0
                    if user_id != "Unknown" and user_id is not None:
                        try:
                            final_uid = int(user_id)
                        except Exception:
                            final_uid = 0
                    
                    self._on_pcm(final_uid, now, pcm)
            except Exception as e:
                logger.error(f"Error forwarding PCM: {e}")

    def cleanup(self):
        logger.info("Sink cleanup called.")
        with self.lock:
            for buf in self.user_data.values():
                buf.close()
            self.user_data.clear()