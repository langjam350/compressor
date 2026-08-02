from typing import Callable, Iterator, Optional
import os
import re
import time

import numpy as np
import pyaudio
import speech_recognition as sr

try:
    from openwakeword.model import Model as _OWWModel
except ImportError:  # openwakeword is optional; cloud-STT fallback still works without it
    _OWWModel = None

# openWakeWord expects 16 kHz mono 16-bit frames; 1280 samples = 80 ms per frame.
_OWW_SAMPLE_RATE = 16000
_OWW_FRAME_SAMPLES = 1280


def extract_query(text: str, wake_word: str) -> Optional[str]:
    pattern = rf'\b{re.escape(wake_word)}\b'
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    query = text[match.end():].strip()
    return query if query else None


class SpeechListener:
    def __init__(
        self,
        wake_word: str,
        on_wake: Optional[Callable[[], None]] = None,
        wake_model_path: str = "models/compressor.onnx",
        wake_threshold: float = 0.5,
    ):
        self.wake_word = wake_word.lower()
        self._recognizer = sr.Recognizer()
        self._on_wake = on_wake
        self._wake_model_path = wake_model_path
        self._wake_threshold = wake_threshold

    def listen_for_commands(self) -> Iterator[str]:
        if _OWWModel is not None and os.path.exists(self._wake_model_path):
            yield from self._listen_openwakeword()
        else:
            print(
                f"[Compressor] Wake model not found at '{self._wake_model_path}' — "
                "using cloud STT wake detection. See docs/WAKE-WORD-TRAINING.md to train it."
            )
            yield from self._listen_google()

    # ------------------------------------------------------------------ #
    # Phase 1a: openWakeWord streaming detection (preferred)              #
    # ------------------------------------------------------------------ #

    def _listen_openwakeword(self) -> Iterator[str]:
        model = _OWWModel(
            wakeword_models=[self._wake_model_path],
            inference_framework="onnx",
        )
        pa = pyaudio.PyAudio()
        print(f"[Compressor] Wake model loaded; listening for '{self.wake_word}'...")

        while True:
            # Stream frames through the model until a detection fires.
            stream = pa.open(
                rate=_OWW_SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=_OWW_FRAME_SAMPLES,
            )
            try:
                while True:
                    data = stream.read(_OWW_FRAME_SAMPLES, exception_on_overflow=False)
                    frame = np.frombuffer(data, dtype=np.int16)
                    scores = model.predict(frame)
                    if max(scores.values()) >= self._wake_threshold:
                        break
            finally:
                # Mic must be closed before any TTS or Phase 2 capture.
                stream.stop_stream()
                stream.close()
            model.reset()

            # Inline attempt: the user may have kept talking ("compressor turn
            # on the lights") — grab the remainder with a short window.
            text = self.listen_once(timeout=1.5)
            if text:
                query = extract_query(text, self.wake_word) or text
                print(f"[Compressor] Heard: {query}")
                yield query
                continue

            # Wake word alone — acknowledge, then Phase 2.
            if self._on_wake:
                try:
                    self._on_wake()
                except Exception as e:
                    print(f"[STT Error] on_wake failed: {e}")

            query2 = self.listen_once(timeout=5)
            if query2:
                print(f"[Compressor] Heard: {query2}")
                yield query2
            else:
                print("[Compressor] Standing by.")

    # ------------------------------------------------------------------ #
    # Phase 1b: cloud-STT wake detection (fallback when no model exists)  #
    # ------------------------------------------------------------------ #

    def _listen_google(self) -> Iterator[str]:
        # One-time calibration — mic is opened then immediately closed
        with sr.Microphone() as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=1)
        print(f"[Compressor] Listening for wake word '{self.wake_word}'...")

        while True:
            # Phase 1: open mic, capture audio, close mic before any processing
            try:
                with sr.Microphone() as source:
                    audio = self._recognizer.listen(source, timeout=1, phrase_time_limit=10)
                text = self._recognizer.recognize_google(audio).strip()
            except sr.WaitTimeoutError:
                continue
            except sr.UnknownValueError:
                continue
            except sr.RequestError as e:
                print(f"[STT Error] {e}")
                continue
            except Exception as e:
                print(f"[STT Error] Network/stream error: {e}")
                time.sleep(1)
                continue

            if not re.search(rf'\b{re.escape(self.wake_word)}\b', text, re.IGNORECASE):
                continue  # no wake word — ignore phrase

            query = extract_query(text, self.wake_word)
            if query:
                # Inline: "compressor play music" — mic is closed, yield immediately
                print(f"[Compressor] Heard: {query}")
                yield query  # caller TTS works — mic is not open
                continue

            # Wake word alone — mic is closed, so on_wake TTS plays correctly
            if self._on_wake:
                try:
                    self._on_wake()
                except Exception as e:
                    print(f"[STT Error] on_wake failed: {e}")

            # Phase 2: open mic, capture query, close mic before yielding
            try:
                with sr.Microphone() as source:
                    audio2 = self._recognizer.listen(source, timeout=5, phrase_time_limit=10)
                query2 = self._recognizer.recognize_google(audio2).strip()
                if query2:
                    print(f"[Compressor] Heard: {query2}")
                    yield query2  # caller TTS works — mic is not open
                else:
                    print("[Compressor] Standing by.")
            except (sr.WaitTimeoutError, sr.UnknownValueError):
                print("[Compressor] Standing by.")
            except sr.RequestError as e:
                print(f"[STT Error] {e}")
            except Exception as e:
                print(f"[STT Error] Network/stream error: {e}")
                time.sleep(1)

    def listen_once(self, timeout: float = 5, phrase_time_limit: float = 10) -> Optional[str]:
        """Listen for a single utterance; return recognized text or None on silence/error."""
        try:
            with sr.Microphone() as source:
                audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            text = self._recognizer.recognize_google(audio).strip()
            return text if text else None
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return None
        except sr.RequestError as e:
            print(f"[STT Error] {e}")
            return None
        except Exception as e:
            print(f"[STT Error] Network/stream error: {e}")
            return None
