def test_speak_invokes_engine(mocker):
    mock_init = mocker.patch("src.tts.pyttsx3.init")
    mock_engine = mock_init.return_value

    from src.tts import TTSEngine
    tts = TTSEngine()
    tts.speak("hello world")

    mock_engine.say.assert_called_once_with("hello world")
    mock_engine.runAndWait.assert_called_once()


def test_speak_empty_string_does_nothing(mocker):
    mock_init = mocker.patch("src.tts.pyttsx3.init")
    mock_engine = mock_init.return_value

    from src.tts import TTSEngine
    tts = TTSEngine()
    tts.speak("")

    mock_engine.say.assert_not_called()
