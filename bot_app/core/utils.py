import datetime
import os

def get_msc_now() -> datetime.datetime:
    """Returns current time in Moscow timezone (UTC+3)."""
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    msc_tz = datetime.timezone(datetime.timedelta(hours=3))
    return utc_now.astimezone(msc_tz)

def format_abs_ts(ts: float) -> str:
    """Formats timestamp to HH:MM:SS in MSC."""
    utc_dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    msc_tz = datetime.timezone(datetime.timedelta(hours=3))
    return utc_dt.astimezone(msc_tz).strftime("%H:%M:%S")

def safe_dirname(name: str) -> str:
    keep_chars = set(" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
    return "".join(c if c in keep_chars else "_" for c in (name or "guild")).strip() or "guild"

def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

def fmt_bytes(num: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}TB"
