import io
import random
from pydub import AudioSegment
import numpy as np

def reconstruct_user_audio(packets, chunk_start, chunk_end, max_silence_s=2.0):
    FRAME_RATE = 48000
    CHANNELS = 2
    SAMPLE_WIDTH = 2
    BYTES_PER_SECOND = FRAME_RATE * CHANNELS * SAMPLE_WIDTH  # 192000
    
    packets.sort(key=lambda x: x[0])
    output = io.BytesIO()
    
    if not packets:
        return AudioSegment.silent(duration=0)
    
    # Pre-fill silence if the user started late relative to chunk start
    # This maintains synchronization with other users in the mix
    start_delay = packets[0][0] - chunk_start
    if start_delay > 0.1: # Only if significant delay (>100ms)
        # Cap initial silence to max_silence_s to save space/money?
        # No, for MIX sync we must be accurate or cap it intelligently.
        # But if we want to save Azure money, we trim start anyway in ChunkProcessor.
        # So here we just align to the requested start.
        silence_bytes = int(start_delay * BYTES_PER_SECOND)
        silence_bytes -= (silence_bytes % 4)
        if silence_bytes > 0:
            output.write(b"\x00" * silence_bytes)

    last_ts = packets[0][0]
    # We track the "end of the last packet written" in timestamp domain
    
    for i, (ts, pcm) in enumerate(packets):
        if not pcm: continue
        
        # Calculate gap from previous packet
        # Initial iteration: gap is 0 (ts - last_ts)
        if i > 0:
            gap = ts - last_ts
            
            # Threshold: 60ms (3 packets) to ignore jitter
            if gap > 0.06:
                # Significant gap -> Insert Silence
                silence_dur = gap
                
                # Squash logic (Optional, currently DISABLED for quality)
                # if silence_dur > max_silence_s: silence_dur = max_silence_s
                
                silence_bytes = int(silence_dur * BYTES_PER_SECOND)
                silence_bytes -= (silence_bytes % 4)
                
                if silence_bytes > 0:
                    output.write(b"\x00" * silence_bytes)
        
        output.write(pcm)
        
        # Update pointer
        dur = len(pcm) / BYTES_PER_SECOND
        last_ts = ts + dur

    raw = output.getvalue()
    if not raw:
        return AudioSegment.silent(duration=0)

    return AudioSegment(data=raw, sample_width=SAMPLE_WIDTH, frame_rate=FRAME_RATE, channels=CHANNELS)

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