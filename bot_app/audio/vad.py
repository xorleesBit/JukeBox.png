import os
import logging
import numpy as np
import onnxruntime
import aiohttp
import asyncio

logger = logging.getLogger(__name__)

# Ссылка на стабильную версию модели (v4)
MODEL_URL = "https://github.com/snakers4/silero-vad/raw/v4.0.0/files/silero_vad.onnx"
MODEL_PATH = "silero_vad.onnx"

class VADValidator:
    def __init__(self):
        self.session = None
        self._download_lock = asyncio.Lock()

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
            # Если не скачалось асинхронно, пробуем синхронно или падаем (но лучше не падать)
            # В реальном worker'е мы вызовем prepare() заранее
            raise FileNotFoundError("VAD model not found")

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(MODEL_PATH, providers=['CPUExecutionProvider'], sess_options=opts)

    def validate(self, audio_segment, min_speech_duration_ms=250) -> bool:
        """
        Returns True if audio contains speech longer than min_speech_duration_ms.
        """
        try:
            self._init_session()
        except Exception:
            return True 

        target_sr = 16000
        if audio_segment.frame_rate != target_sr:
            audio_segment = audio_segment.set_frame_rate(target_sr)
        if audio_segment.channels > 1:
            audio_segment = audio_segment.set_channels(1)

        samples = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)
        samples = samples.astype(np.float32) / 32768.0

        window_size_samples = 512 # 32ms
        
        h = np.zeros((2, 1, 64), dtype=np.float32)
        c = np.zeros((2, 1, 64), dtype=np.float32)
        sr = np.array(target_sr, dtype=np.int64)

        speech_threshold = 0.5 # Slightly stricter
        speech_chunks_count = 0
        
        for i in range(0, len(samples), window_size_samples):
            chunk = samples[i:i+window_size_samples]
            if len(chunk) < window_size_samples:
                pad = window_size_samples - len(chunk)
                chunk = np.pad(chunk, (0, pad), 'constant')
            
            input_tensor = chunk[np.newaxis, :]
            
            ort_inputs = {'input': input_tensor, 'sr': sr, 'h': h, 'c': c}
            output, h, c = self.session.run(None, ort_inputs)
            
            if output[0][0] > speech_threshold:
                speech_chunks_count += 1

        # Calculate total speech duration
        # Each chunk is 512 samples @ 16000Hz = 0.032 seconds (32ms)
        total_speech_ms = speech_chunks_count * 32
        
        return total_speech_ms >= min_speech_duration_ms

# Global instance
vad = VADValidator()
