from typing import Callable, Iterator, Optional
import re
import time
import speech_recognition as sr


def extract_query(text: str, wake_word: str) -> Optional[str]:
    pattern = rf'\b{re.escape(wake_word)}\b'
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    query = text[match.end():].strip()
    return query if query else None


class SpeechListener:
    def __init__(self, wake_word: str, on_wake: Optional[Callable[[], None]] = None):
        self.wake_word = wake_word.lower()
        self._recognizer = sr.Recognizer()
        self._on_wake = on_wake

    def listen_for_commands(self) -> Iterator[str]:
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
