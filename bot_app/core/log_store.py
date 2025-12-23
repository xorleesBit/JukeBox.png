import os
import json
import time
import datetime
import threading
from collections import deque

from .utils import format_abs_ts


class LogStore:
    """
    Canonical storage: YYYY-MM-DD.events.log (JSONL UTF-8).
    Human readable: YYYY-MM-DD.log rebuilt from JSONL sorted by ts.
    """
    def __init__(self, base_dir: str, rebuild_debounce_sec: float = 1.0, write_bom_for_human_log: bool = True):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

        self.rebuild_debounce_sec = float(rebuild_debounce_sec)
        self.write_bom_for_human_log = bool(write_bom_for_human_log)

        self._lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}

    def _day_str(self, ts: float) -> str:
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d")

    def events_log_path(self, day_str: str) -> str:
        return os.path.join(self.base_dir, f"{day_str}.events.log")

    def human_log_path(self, day_str: str) -> str:
        return os.path.join(self.base_dir, f"{day_str}.log")

    def list_days(self) -> list[str]:
        try:
            days = set()
            for fn in os.listdir(self.base_dir):
                if fn.endswith(".events.log"):
                    # Extract date from YYYY-MM-DD.events.log
                    days.add(fn.split(".")[0])
                if fn.endswith(".log") and not fn.endswith(".events.log") and len(fn) == 14: # YYYY-MM-DD.log
                    days.add(fn.split(".")[0])
            return sorted(list(days))
        except Exception:
            return []

    def latest_day_str(self) -> str | None:
        days = self.list_days()
        return days[-1] if days else None

    def append_event(self, ts: float, icon: str, text: str):
        day = self._day_str(ts)
        rec = {"ts": float(ts), "icon": icon, "text": text}

        with self._lock:
            with open(self.events_log_path(day), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        self.schedule_rebuild(day)

    def schedule_rebuild(self, day_str: str):
        with self._lock:
            t = self._timers.get(day_str)
            if t:
                try:
                    t.cancel()
                except Exception:
                    pass
            timer = threading.Timer(self.rebuild_debounce_sec, self.rebuild_day_log, args=(day_str,))
            timer.daemon = True
            self._timers[day_str] = timer
            timer.start()

    def rebuild_day_log(self, day_str: str):
        src = self.events_log_path(day_str)
        dst = self.human_log_path(day_str)
        tmp = dst + ".tmp"

        rows = []
        with self._lock:
            if not os.path.exists(src):
                return
            try:
                with open(src, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            rows.append((float(obj.get("ts", 0.0)), obj.get("icon", "⋯"), obj.get("text", "")))
                        except Exception:
                            continue
            except Exception:
                return

        rows.sort(key=lambda x: x[0])

        enc = "utf-8-sig" if self.write_bom_for_human_log else "utf-8"

        try:
            with open(tmp, "w", encoding=enc) as out:
                for ts, icon, text in rows:
                    out.write(f"[{format_abs_ts(ts)}] {icon} {text}\n")
            os.replace(tmp, dst)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def ensure_rebuilt(self, ts: float):
        self.rebuild_day_log(self._day_str(ts))

    def day_human_log_path_for_ts(self, ts: float) -> str:
        return self.human_log_path(self._day_str(ts))

    def tail_events(self, day_str: str, n: int = 30) -> list[str]:
        p = self.events_log_path(day_str)
        if not os.path.exists(p):
            return []

        dq = deque(maxlen=max(1, int(n)))
        try:
            with self._lock:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            dq.append(line)
        except Exception:
            return []

        rows = []
        for line in dq:
            try:
                obj = json.loads(line)
                ts = float(obj.get("ts", 0.0))
                icon = obj.get("icon", "⋯")
                text = obj.get("text", "")
                rows.append((ts, f"[{format_abs_ts(ts)}] {icon} {text}"))
            except Exception:
                continue

        rows.sort(key=lambda x: x[0])
        return [s for _, s in rows]