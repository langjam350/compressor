from typing import Optional, Iterator
import speech_recognition as sr


def extract_query(text: str, wake_word: str) -> Optional[str]:
    lower = text.lower()
    if wake_word not in lower:
        return None
    idx = lower.index(wake_word) + len(wake_word)
    query = lower[idx:].strip()
    return query if query else None


class SpeechListener:
    def __init__(self, wake_word: str):
        self.wake_word = wake_word.lower()
        self._recognizer = sr.Recognizer()

    def listen_for_commands(self) -> Iterator[str]:
        with sr.Microphone() as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=1)
            print(f"[Condensor] Listening for wake word '{self.wake_word}'...")
            while True:
                try:
                    audio = self._recognizer.listen(source, timeout=1, phrase_time_limit=10)
                    text = self._recognizer.recognize_google(audio)
                    query = extract_query(text, self.wake_word)
                    if query:
                        print(f"[Condensor] Heard: {query}")
                        yield query
                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as e:
                    print(f"[STT Error] {e}")
                    continue
