import os
import re
import datetime

BAD_CHARS = '<>:"/\\|?*'

def safe_dirname(name: str) -> str:
    out = "".join("_" if c in BAD_CHARS else c for c in (name or "guild"))
    return out.strip() or "guild"

def fmt_bytes(n: int) -> str:
    n = int(max(0, n))
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{int(f)} {u}" if u == "B" else f"{f:.2f} {u}"
        f /= 1024.0
    return f"{n} B"

def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def format_abs_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")

def hour_key_from_ts(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d_%H")

def tail_lines(path: str, n: int = 30) -> str:
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 2048
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                step = block if size - block > 0 else size
                size -= step
                f.seek(size)
                data = f.read(step) + data
            txt = data.decode("utf-8", errors="ignore").splitlines()[-n:]
            return "\n".join(txt)
    except Exception:
        return ""

def is_hour_file(fn: str) -> bool:
    return bool(re.fullmatch(r"\d{2}\.txt", fn))
