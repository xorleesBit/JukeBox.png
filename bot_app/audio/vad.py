import os
import logging
import numpy as np
import onnxruntime
import aiohttp
import asyncio

logger = logging.getLogger(__name__)

# Используем Silero VAD v6.2 (путь src/silero_vad/data/silero_vad.onnx)
MODEL_URL = "https://github.com/snakers4/silero-vad/raw/v6.2/src/silero_vad/data/silero_vad.onnx"
MODEL_PATH = "silero_vad.onnx"

class VADValidator:
    def __init__(self):
        self.session = None
        self._download_lock = asyncio.Lock()
        self.version = 5 # Default assumption, detected later

    async def _ensure_model(self):
        if os.path.exists(MODEL_PATH):
            return
        
        async with self._download_lock:
            if os.path.exists(MODEL_PATH): return
            
            logger.info(f"Downloading VAD model from {MODEL_URL}...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(MODEL_URL) as resp:
                        if resp.status == 200:
                            with open(MODEL_PATH, "wb") as f:
                                f.write(await resp.read())
                            logger.info("VAD model downloaded.")
                        else:
                            logger.error(f"Failed to download VAD model: {resp.status}")
            except Exception as e:
                logger.error(f"VAD download error: {e}")

    def _init_session(self):
        if self.session:
            return
        
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError("VAD model not found")

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        
        self.session = onnxruntime.InferenceSession(MODEL_PATH, providers=['CPUExecutionProvider'], sess_options=opts)
        
        # Detect Model Version by Inputs
        inp_names = [i.name for i in self.session.get_inputs()]
        if 'state' in inp_names:
            self.version = 5
            logger.info("VAD: Detected v5+ architecture (single state).")
        elif 'h' in inp_names and 'c' in inp_names:
            self.version = 3
            logger.info("VAD: Detected v3/v4 architecture (split state).")
        else:
            logger.warning(f"VAD: Unknown input signature {inp_names}, defaulting to v5 logic.")
            self.version = 5

    def validate(self, audio_segment, min_speech_duration_ms=250) -> bool:
        """
        Returns True if audio contains speech longer than min_speech_duration_ms.
        """
        try:
            self._init_session()
        except Exception:
            return True # Fallback: allow all

        # Prepare Audio
        target_sr = 16000
        if audio_segment.frame_rate != target_sr:
            audio_segment = audio_segment.set_frame_rate(target_sr)
        if audio_segment.channels > 1:
            audio_segment = audio_segment.set_channels(1)

        samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)
        samples = samples / 32768.0 # Normalize short to float

        # Config
        window_size_samples = 512 # 32ms
        speech_threshold = 0.5
        speech_chunks_count = 0
        
        # Prepare Tensors based on Version
        sr = np.array([target_sr], dtype=np.int64)
        
        # State Initialization
        if self.version == 5:
            # v5: state shape (2, 1, 128)
            state = np.zeros((2, 1, 128), dtype=np.float32)
            h, c = None, None
        else:
            # v3/v4: h, c shapes (2, 1, 64)
            h = np.zeros((2, 1, 64), dtype=np.float32)
            c = np.zeros((2, 1, 64), dtype=np.float32)
            state = None

        # Loop
        for i in range(0, len(samples), window_size_samples):
            chunk = samples[i:i+window_size_samples]
            if len(chunk) < window_size_samples:
                pad = window_size_samples - len(chunk)
                chunk = np.pad(chunk, (0, pad), 'constant')
            
            input_tensor = chunk[np.newaxis, :] # (1, 512)
            
            # Run Inference
            if self.version == 5:
                ort_inputs = {'input': input_tensor, 'state': state, 'sr': sr}
                # Output: probability, state
                out = self.session.run(None, ort_inputs)
                prob = out[0]
                state = out[1] # Update state for next chunk
            else:
                ort_inputs = {'input': input_tensor, 'sr': sr, 'h': h, 'c': c}
                # Output: probability, h, c
                out = self.session.run(None, ort_inputs)
                prob = out[0]
                h, c = out[1], out[2] # Update states
            
            if prob[0][0] > speech_threshold:
                speech_chunks_count += 1

        total_speech_ms = speech_chunks_count * 32
        return total_speech_ms >= min_speech_duration_ms

# Global instance
vad = VADValidator()