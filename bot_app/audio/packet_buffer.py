import struct
import tempfile
import os

class DiskPacketBuffer:
    """
    Stores audio packets (timestamp + pcm) in a temporary file 
    to avoid high RAM usage during long recording sessions.
    """
    def __init__(self):
        self._f = tempfile.TemporaryFile(mode="w+b")
        self._count = 0

    def append(self, ts: float, pcm: bytes):
        if not pcm: return
        # Format: TS (double, 8b) | Length (int, 4b) | PCM Data
        header = struct.pack("di", ts, len(pcm))
        self._f.write(header)
        self._f.write(pcm)
        self._count += 1

    def read_all(self) -> list[tuple[float, bytes]]:
        """
        Reads all packets back into memory. 
        Note: This is intended to be called once during processing.
        """
        self._f.seek(0)
        packets = []
        try:
            while True:
                header = self._f.read(12) # 8 + 4
                if len(header) < 12:
                    break
                ts, length = struct.unpack("di", header)
                pcm = self._f.read(length)
                if len(pcm) < length:
                    break # corrupted or truncated
                packets.append((ts, pcm))
        except Exception:
            pass
        return packets

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass

    def __del__(self):
        self.close()
