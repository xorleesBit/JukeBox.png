import logging
import numpy as np
from pydub import AudioSegment

logger = logging.getLogger(__name__)

def reconstruct_user_audio(packets: list, start_ts: float = None, end_ts: float = None) -> AudioSegment:
    """
    Reconstructs user audio with De-Jitter logic.
    Fixes 'stuttering' by snapping jittery packets to a continuous grid,
    while preserving true DTX pauses.
    """
    if not packets:
        return AudioSegment.silent(duration=0)

    # 1. Sort
    packets.sort(key=lambda x: x[0])
    
    # 2. Audio Params
    SAMPLE_RATE = 48000
    CHANNELS = 2
    SAMPLE_WIDTH = 2
    BYTES_PER_SAMPLE = 4 # 2 channels * 2 bytes
    SAMPLES_PER_MS = 48 # 48000 / 1000
    FRAME_DURATION_MS = 20 # Standard Discord frame
    FRAME_SAMPLES = 960 # 20ms * 48khz
    
    # 3. De-Jitter / Timestamp Correction
    # We build a list of (corrected_offset_samples, pcm_data)
    
    aligned_chunks = []
    
    base_ts = start_ts if start_ts is not None else packets[0][0]
    
    # Cursor tracks where the NEXT packet "should" start in a continuous stream
    # relative to base_ts (in seconds)
    expected_next_ts = packets[0][0] - base_ts
    
    # If the first packet is way after start_ts, we respect that initial silence
    # But we treat the first packet's arrival as the anchor for the stream
    if expected_next_ts < 0: expected_next_ts = 0
    
    for ts, pcm in packets:
        # Current packet's relative arrival time
        rel_ts = ts - base_ts
        if rel_ts < 0: rel_ts = 0
        
        # Calculate gap from expected
        diff = rel_ts - expected_next_ts
        
        # Jitter Threshold: 60ms (0.06s). 
        # If gap is smaller than this, it's just lag -> Snap to expected.
        # If gap is larger, it's silence -> Move cursor to actual.
        if diff > 0.06:
            # Real silence (DTX)
            write_ts = rel_ts
        elif diff < -0.06:
            # Overlap/Out of order? (Should be rare with sort)
            # We just place it where it says, or skip?
            # Let's trust timestamp if it's WAY off, but usually we just snap.
            write_ts = rel_ts
        else:
            # Jitter -> Snap to continuous
            write_ts = expected_next_ts
            
        # Convert to samples
        start_sample = int(write_ts * SAMPLE_RATE)
        
        aligned_chunks.append((start_sample, pcm))
        
        # Advance cursor
        # Calculate duration of THIS packet from bytes
        # len(pcm) / 4 bytes_per_sample = num_samples
        packet_samples = len(pcm) // BYTES_PER_SAMPLE
        packet_duration_s = packet_samples / SAMPLE_RATE
        
        expected_next_ts = write_ts + packet_duration_s

    if not aligned_chunks:
        return AudioSegment.silent(duration=0)

    # 4. Determine total size
    last_start, last_pcm = aligned_chunks[-1]
    last_len = len(last_pcm) // BYTES_PER_SAMPLE
    
    total_samples_needed = last_start + last_len
    
    # If end_ts provided, ensure we cover it (or trim?)
    # Usually we just want the audio content. Padding to end_ts happens in mixing.
    # But let's respect end_ts if it implies longer silence at end.
    if end_ts is not None:
        req_duration = end_ts - base_ts
        req_samples = int(req_duration * SAMPLE_RATE)
        if req_samples > total_samples_needed:
            total_samples_needed = req_samples

    # 5. Build Canvas
    # Shape: (N, 2) for stereo, or flat (N*2,). 
    # Working with flat int16 array is easiest for pydub.
    # Size = samples * channels
    canvas_size = total_samples_needed * CHANNELS
    
    # Align to even
    if canvas_size % 2 != 0: canvas_size += 1
    
    canvas = np.zeros(canvas_size, dtype=np.int16)
    
    # 6. Paint
    for start_sample, pcm in aligned_chunks:
        # pcm is bytes -> int16
        packet_arr = np.frombuffer(pcm, dtype=np.int16)
        
        # start_sample is in "stereo frames". Array index is * 2.
        idx_start = start_sample * CHANNELS
        idx_end = idx_start + len(packet_arr)
        
        if idx_end > len(canvas):
            packet_arr = packet_arr[:len(canvas)-idx_start]
            idx_end = idx_start + len(packet_arr)
            
        canvas[idx_start:idx_end] = packet_arr
        
    return AudioSegment(
        data=canvas.tobytes(),
        sample_width=SAMPLE_WIDTH,
        frame_rate=SAMPLE_RATE,
        channels=CHANNELS
    )

def get_speech_segments(packets: list, gap_threshold: float = 1.5) -> list:
    """
    Clusters packets into segments based on time gaps for STT API.
    Returns: list of {'start': float, 'packets': list, 'end': float}
    """
    if not packets: return []
    # Ensure sorted
    packets.sort(key=lambda x: x[0])
    
    segments = []
    current_packets = [packets[0]]
    
    for i in range(1, len(packets)):
        # 20ms frame assumption
        prev_end = packets[i-1][0] + 0.02 
        curr_start = packets[i][0]
        
        if curr_start - prev_end > gap_threshold:
            # Close current segment
            segments.append({
                'start': current_packets[0][0],
                'end': prev_end,
                'packets': current_packets
            })
            current_packets = []
        current_packets.append(packets[i])
    
    if current_packets:
        last_end = current_packets[-1][0] + 0.02
        segments.append({
            'start': current_packets[0][0],
            'end': last_end,
            'packets': current_packets
        })
        
    return segments

def apply_effect(audio: AudioSegment, effect_name: str) -> AudioSegment:
    if not effect_name: return audio
    effect_name = effect_name.lower()
    
    if effect_name == 'helium':
        sound_with_altered_frame_rate = audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 1.5)
        })
        return sound_with_altered_frame_rate.set_frame_rate(audio.frame_rate)

    elif effect_name == 'demon':
        sound_with_altered_frame_rate = audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 0.75)
        })
        return sound_with_altered_frame_rate.set_frame_rate(audio.frame_rate)

    elif effect_name == 'reverb':
        delay_ms = 100
        silence = AudioSegment.silent(duration=delay_ms)
        delayed_1 = silence + audio - 4
        delayed_2 = AudioSegment.silent(duration=delay_ms*2) + audio - 8
        mixed = audio.overlay(delayed_1).overlay(delayed_2)
        return mixed
        
    return audio
