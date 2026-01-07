import logging
import numpy as np
from pydub import AudioSegment

logger = logging.getLogger(__name__)

def reconstruct_user_audio(packets: list, start_ts: float = None, end_ts: float = None, sample_rate: int = 48000, channels: int = 2) -> np.ndarray:
    """
    Reconstructs user audio with De-Jitter logic.
    Fixes 'stuttering' by snapping jittery packets to a continuous grid.
    """
    if not packets:
        return np.array([], dtype=np.int16)

    # 1. Sort
    packets.sort(key=lambda x: x[0])
    
    # 2. Audio Params
    # Input is always 48000 Stereo (Discord Standard)
    IN_RATE = 48000
    IN_CHANNELS = 2
    
    SAMPLE_WIDTH = 2
    BYTES_PER_SAMPLE = channels * SAMPLE_WIDTH
    
    # 3. De-Jitter / Timestamp Correction
    aligned_chunks = []
    base_ts = start_ts if start_ts is not None else packets[0][0]
    expected_next_ts = packets[0][0] - base_ts
    if expected_next_ts < 0: expected_next_ts = 0
    
    for ts, pcm in packets:
        rel_ts = ts - base_ts
        if rel_ts < 0: rel_ts = 0
        
        diff = rel_ts - expected_next_ts
        if diff > 0.06:
            write_ts = rel_ts
        elif diff < -0.06:
            write_ts = rel_ts
        else:
            write_ts = expected_next_ts
            
        start_sample = int(write_ts * sample_rate)
        
        # --- Conversion Logic (Input 48k Stereo -> Target) ---
        packet_arr = np.frombuffer(pcm, dtype=np.int16)
        
        # 1. Convert to Mono if needed
        if channels == 1 and IN_CHANNELS == 2:
            # Reshape to (N, 2), then mean across channels
            packet_arr = packet_arr.reshape(-1, 2).mean(axis=1).astype(np.int16)
        
        # 2. Downsample if needed (48k -> 16k is factor of 3)
        if sample_rate == 16000 and IN_RATE == 48000:
            packet_arr = packet_arr[::3]
        
        aligned_chunks.append((start_sample, packet_arr))
        
        # Advance cursor (based on target sample rate)
        packet_samples = len(packet_arr) // channels
        packet_duration_s = packet_samples / sample_rate
        expected_next_ts = write_ts + packet_duration_s

    if not aligned_chunks:
        return np.array([], dtype=np.int16)

    # 4. Determine total size
    last_start, last_pcm_arr = aligned_chunks[-1]
    last_len = len(last_pcm_arr) // channels
    total_samples_needed = last_start + last_len
    
    if end_ts is not None:
        req_duration = end_ts - base_ts
        req_samples = int(req_duration * sample_rate)
        if req_samples > total_samples_needed:
            total_samples_needed = req_samples

    # 5. Build Canvas
    canvas_size = total_samples_needed * channels
    canvas = np.zeros(canvas_size, dtype=np.int16)
    
    # 6. Paint
    for start_sample, p_arr in aligned_chunks:
        idx_start = start_sample * channels
        
        if idx_start < 0: 
            skip = abs(idx_start)
            if skip >= len(p_arr): continue
            p_arr = p_arr[skip:]
            idx_start = 0

        if idx_start >= len(canvas):
            continue

        idx_end = idx_start + len(p_arr)
        if idx_end > len(canvas):
            p_arr = p_arr[:len(canvas)-idx_start]
            idx_end = idx_start + len(p_arr)
        
        if len(p_arr) == 0: continue
        canvas[idx_start:idx_end] = p_arr
        
    return canvas

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
