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

    def read_all(self, buffer_size: int = 65536) -> list[tuple[float, bytes]]:
        """
        Reads all packets back into memory with buffering.
        Optimized to reduce system calls and improve I/O performance.
        
        Args:
            buffer_size: Size of read buffer (default 64KB)
            
        Returns:
            List of (timestamp, pcm_data) tuples
        """
        self._f.seek(0)
        packets = []
        
        # Buffer for reading
        read_buffer = bytearray()
        header_size = 12  # 8 (double) + 4 (int)
        
        try:
            while True:
                # Refill buffer if needed
                if len(read_buffer) < header_size:
                    chunk = self._f.read(buffer_size)
                    if not chunk:
                        break
                    read_buffer.extend(chunk)
                
                if len(read_buffer) < header_size:
                    break
                
                # Parse header
                ts, length = struct.unpack("di", read_buffer[:header_size])
                
                # Ensure we have enough data for PCM
                total_needed = header_size + length
                while len(read_buffer) < total_needed:
                    chunk = self._f.read(buffer_size)
                    if not chunk:
                        break
                    read_buffer.extend(chunk)
                
                if len(read_buffer) < total_needed:
                    break  # Corrupted or truncated
                
                # Extract PCM data
                pcm = bytes(read_buffer[header_size:total_needed])
                packets.append((ts, pcm))
                
                # Remove processed data from buffer
                read_buffer = read_buffer[total_needed:]
                
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
