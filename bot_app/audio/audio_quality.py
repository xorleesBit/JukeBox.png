import os
from pydub import AudioSegment


def pcm_to_mp3_pydub(
    pcm_bytes: bytes,
    mp3_path: str,
    *,
    frame_rate: int = 48000,
    channels: int = 2,
    sample_width: int = 2,
    bitrate: str = "192k",
) -> bool:
    """
    Export quality like your example: AudioSegment(data=raw, ...) -> export(mp3). [web:461]
    """
    try:
        if not pcm_bytes:
            return False
        os.makedirs(os.path.dirname(mp3_path), exist_ok=True)

        seg = AudioSegment(
            data=pcm_bytes,
            sample_width=int(sample_width),
            frame_rate=int(frame_rate),
            channels=int(channels),
        )

        # Keep stereo like the example; set bitrate explicitly for stable quality.
        seg.export(mp3_path, format="mp3", bitrate=str(bitrate))
        return os.path.exists(mp3_path)
    except Exception:
        return False


def mp3_to_wav_for_azure(mp3_path: str, wav_path: str) -> bool:
    """
    Azure in your example transcribes WAV written to disk; do the same. [web:469]
    """
    try:
        if not os.path.exists(mp3_path):
            return False
        os.makedirs(os.path.dirname(wav_path), exist_ok=True)

        seg = AudioSegment.from_file(mp3_path)
        seg.export(wav_path, format="wav")
        return os.path.exists(wav_path)
    except Exception:
        return False
