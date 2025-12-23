import io
import random
from pydub import AudioSegment

def reconstruct_user_audio(packets, chunk_start, chunk_end):
    FRAME_RATE = 48000
    CHANNELS = 2
    SAMPLE_WIDTH = 2
    BYTES_PER_SECOND = FRAME_RATE * CHANNELS * SAMPLE_WIDTH  # 192000
    SILENCE_THRESHOLD = 0.1

    packets.sort(key=lambda x: x[0])
    output = io.BytesIO()
    last_audio_end_time = chunk_start

    for ts, pcm in packets:
        if not pcm:
            continue
        dur = len(pcm) / BYTES_PER_SECOND
        gap = ts - last_audio_end_time
        if gap > SILENCE_THRESHOLD:
            silence = int(gap * BYTES_PER_SECOND)
            silence -= (silence % 4)
            if silence > 0:
                output.write(b"\x00" * silence)
            last_audio_end_time += gap
        output.write(pcm)
        last_audio_end_time += dur

    raw = output.getvalue()
    if not raw:
        return AudioSegment.silent(duration=0)

    return AudioSegment(data=raw, sample_width=SAMPLE_WIDTH, frame_rate=FRAME_RATE, channels=CHANNELS)

def apply_effect(audio: AudioSegment, effect_name: str) -> AudioSegment:
    """
    Applies audio effects: 'helium', 'demon', 'reverb'.
    """
    if not effect_name:
        return audio
        
    effect_name = effect_name.lower()
    
    if effect_name == 'helium':
        # Pitch up: Increase sample rate then override to original
        # This speeds up audio and pitches it up. To keep duration, we'd need time stretching, 
        # but simple pitch shift usually involves speed change or complex DSP.
        # Simple "Chipmunk" effect: increase speed.
        new_rate = int(audio.frame_rate * 1.5)
        # set_frame_rate just changes the metadata (plays faster/higher)
        # We want to RESAMPLE to that rate, effectively pitching up if we play at normal rate?
        # No, pydub logic:
        # spawn(override_frame_rate) -> plays faster.
        # set_frame_rate -> resamples.
        
        # To pitch shift up without changing duration is hard.
        # To pitch shift up AND speed up (Helium style) is easy:
        # Just tell the player it has a lower sample rate? No.
        
        # Pydub way for simple pitch shift (affects speed):
        sound_with_altered_frame_rate = audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 1.5)
        })
        return sound_with_altered_frame_rate.set_frame_rate(audio.frame_rate)

    elif effect_name == 'demon':
        # Pitch down (affects speed - slows down)
        sound_with_altered_frame_rate = audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 0.75)
        })
        return sound_with_altered_frame_rate.set_frame_rate(audio.frame_rate)

    elif effect_name == 'reverb':
        # Simple delay based reverb
        # Mix original with delayed versions
        delay_ms = 100
        decay = 0.6
        
        # Create a delayed copy
        delayed = audio - 5 # slightly quieter start? No, attenuation.
        
        # Pydub doesn't have easy delay. We prepend silence.
        silence = AudioSegment.silent(duration=delay_ms)
        delayed_1 = silence + audio
        delayed_1 = delayed_1 - 4 # Reduce volume by 4dB
        
        delayed_2 = AudioSegment.silent(duration=delay_ms*2) + audio
        delayed_2 = delayed_2 - 8 # Reduce volume
        
        # Overlay. Note: this extends duration.
        mixed = audio.overlay(delayed_1)
        mixed = mixed.overlay(delayed_2)
        return mixed
        
    return audio