import time
import threading


class WordsAccumulator:
    def __init__(self):
        self._lock = threading.Lock()
        self._start_ts = time.time()
        self._data = {}  # user_id -> dict(text,audio,prank)

    def add_words(self, user_id: int, text_words=0, audio_words=0, prank_words=0):
        with self._lock:
            d = self._data.get(user_id)
            if d is None:
                d = {"text": 0, "audio": 0, "prank": 0}
                self._data[user_id] = d
            d["text"] += int(text_words)
            d["audio"] += int(audio_words)
            d["prank"] += int(prank_words)

    def snapshot_and_reset(self):
        with self._lock:
            start = self._start_ts
            end = time.time()
            snap = self._data
            self._data = {}
            self._start_ts = end
        return start, end, snap
