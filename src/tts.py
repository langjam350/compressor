import pyttsx3


class TTSEngine:
    def __init__(self, rate: int = 175):
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", rate)

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return
        self._engine.say(text)
        self._engine.runAndWait()
