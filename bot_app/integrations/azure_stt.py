import os
import re
import gc
import json
import threading
import logging

from bot_app.core.config import AZURE_SPEECH_KEY, AZURE_SERVICE_REGION, AZURE_LANGUAGE

logger = logging.getLogger(__name__)

TICKS_PER_SEC = 10_000_000

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None
    logger.warning("Azure Speech SDK not installed or import failed.")


def _azure_words_from_result_json(result_json: str):
    try:
        obj = json.loads(result_json)
    except Exception:
        return []
    nbest = obj.get("NBest", [])
    if not nbest:
        return []
    return nbest[0].get("Words", [])


def _words_to_sentences(words, abs_chunk_start_ts: float, user_name: str, pause_split_sec: float = 0.8):
    out = []
    buf = []
    sent_start_abs = None
    prev_end_sec = None

    def flush(end_abs):
        nonlocal buf, sent_start_abs
        if not buf:
            return
        text = " ".join(buf).strip()
        if text:
            out.append((sent_start_abs or end_abs, f"{user_name}: {text}"))
        buf = []
        sent_start_abs = None

    for w in words:
        token = (w.get("Word") or "").strip()
        off = int(w.get("Offset", 0))
        dur = int(w.get("Duration", 0))
        start_sec = off / TICKS_PER_SEC
        end_sec = (off + dur) / TICKS_PER_SEC

        if not token:
            prev_end_sec = end_sec
            continue

        if sent_start_abs is None:
            sent_start_abs = abs_chunk_start_ts + start_sec

        if prev_end_sec is not None and (start_sec - prev_end_sec) > pause_split_sec:
            flush(abs_chunk_start_ts + prev_end_sec)

        buf.append(token)

        if re.search(r"[.!?…]+$", token):
            flush(abs_chunk_start_ts + end_sec)

        prev_end_sec = end_sec

    flush(abs_chunk_start_ts + (prev_end_sec or 0))
    return out


def transcribe_file_azure_sentences(filename: str, abs_chunk_start_ts: float, user_name: str, duration_sec: float = 300.0):
    if not filename or not os.path.exists(filename):
        logger.error(f"STT Error: File not found: {filename}")
        return []
    if not AZURE_SPEECH_KEY or speechsdk is None:
        logger.error("STT Error: Azure Key missing or SDK not installed.")
        return []

    logger.info(f"Starting STT (Sentences) for {filename} ({user_name})")

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SERVICE_REGION)
    speech_config.speech_recognition_language = AZURE_LANGUAGE

    speech_config.request_word_level_timestamps()
    speech_config.output_format = speechsdk.OutputFormat.Detailed

    audio_config = speechsdk.audio.AudioConfig(filename=filename)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    done = threading.Event()
    sentence_lines = []

    def stop_cb(evt):
        logger.info(f"STT Session stopped for {filename}")
        try:
            recognizer.stop_continuous_recognition()
        except Exception:
            pass
        done.set()
        
    def canceled_cb(evt):
        logger.warning(f"STT Canceled for {filename}: {evt.reason} / {evt.error_details}")
        stop_cb(evt)

    def recognized_cb(evt):
        try:
            r = evt.result
            if not r or not getattr(r, "json", None):
                return
            
            # logger.debug(f"STT Result JSON: {r.json}") # Uncomment for deep debug
            
            words = _azure_words_from_result_json(r.json)
            if words:
                logger.info(f"STT Recognized {len(words)} words for {user_name}")
                sentence_lines.extend(_words_to_sentences(words, abs_chunk_start_ts, user_name))
        except Exception as e:
            logger.error(f"STT Recognized Callback Error: {e}")
            return

    recognizer.recognized.connect(recognized_cb)
    recognizer.session_stopped.connect(stop_cb)
    recognizer.canceled.connect(canceled_cb)

    # Dynamic timeout: at least 3 minutes, or 3x duration
    wait_time = max(180.0, duration_sec * 3.0)
    
    recognizer.start_continuous_recognition()
    if not done.wait(timeout=wait_time):
        logger.error(f"STT Timeout ({wait_time}s) for {filename}")
        try:
            recognizer.stop_continuous_recognition()
        except:
            pass

    try:
        del recognizer, audio_config, speech_config
    except Exception:
        pass
    gc.collect()

    return sentence_lines


def transcribe_file_azure_text(filename: str) -> str:
    """
    Short clip -> text (for prank phrase labeling).
    """
    if not filename or not os.path.exists(filename):
        logger.error(f"STT Short Error: File not found {filename}")
        return ""
    if not AZURE_SPEECH_KEY or speechsdk is None:
        logger.error("STT Short Error: Key missing or SDK missing.")
        return ""

    logger.info(f"Starting STT (Short) for {filename}")

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SERVICE_REGION)
    speech_config.speech_recognition_language = AZURE_LANGUAGE
    speech_config.output_format = speechsdk.OutputFormat.Detailed

    audio_config = speechsdk.audio.AudioConfig(filename=filename)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    done = threading.Event()
    parts = []

    def stop_cb(evt):
        try:
            recognizer.stop_continuous_recognition()
        except Exception:
            pass
        done.set()
        
    def canceled_cb(evt):
        logger.warning(f"STT Short Canceled: {evt.reason} / {evt.error_details}")
        stop_cb(evt)

    def recognized_cb(evt):
        try:
            r = evt.result
            if not r or not getattr(r, "json", None):
                return
            obj = json.loads(r.json)
            nbest = obj.get("NBest") or []
            if nbest:
                txt = (nbest[0].get("Display") or "").strip()
                if txt:
                    logger.info(f"STT Short Recognized: {txt}")
                    parts.append(txt)
        except Exception as e:
            logger.error(f"STT Short Callback Error: {e}")
            return

    recognizer.recognized.connect(recognized_cb)
    recognizer.session_stopped.connect(stop_cb)
    recognizer.canceled.connect(canceled_cb)

    recognizer.start_continuous_recognition()
    if not done.wait(timeout=60):
        logger.error(f"STT Short Timeout (60s) for {filename}")
        try:
            recognizer.stop_continuous_recognition()
        except:
            pass

    try:
        del recognizer, audio_config, speech_config
    except Exception:
        pass
    gc.collect()

    return " ".join(p.strip() for p in parts if p.strip()).strip()