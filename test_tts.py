"""Standalone TTS test — run this directly: py test_tts.py"""
import pyttsx3

engine = pyttsx3.init()

voices = engine.getProperty("voices")
print(f"Available voices ({len(voices)}):")
for i, v in enumerate(voices):
    print(f"  [{i}] {v.id}")

print("\nSpeaking test phrase...")
engine.say("Hello, this is a TTS test. Can you hear me?")
engine.runAndWait()
print("Done.")
