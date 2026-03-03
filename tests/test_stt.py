def test_extract_query_finds_keyword():
    from src.stt import extract_query
    result = extract_query("condensor tell me about mars", "condensor")
    assert result == "tell me about mars"


def test_extract_query_case_insensitive():
    from src.stt import extract_query
    result = extract_query("Condensor How far is Chicago", "condensor")
    assert result == "How far is Chicago"


def test_extract_query_returns_none_when_missing():
    from src.stt import extract_query
    result = extract_query("tell me about mars", "condensor")
    assert result is None


def test_extract_query_returns_none_when_nothing_after_keyword():
    from src.stt import extract_query
    result = extract_query("condensor", "condensor")
    assert result is None


def test_speech_listener_yields_inline_query(mocker):
    """Wake word + query in same phrase → yield query directly, no on_wake call."""
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")

    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.return_value = "condensor play music"

    on_wake = mocker.Mock()
    from src.stt import SpeechListener
    listener = SpeechListener("condensor", on_wake=on_wake)
    gen = listener.listen_for_commands()
    result = next(gen)
    assert result == "play music"
    on_wake.assert_not_called()


def test_speech_listener_two_phase(mocker):
    """Wake word alone → on_wake called → next phrase yielded as query."""
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")

    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.side_effect = [
        "condensor",    # Phase 1: wake word only
        "play music",   # Phase 2: query
    ]

    on_wake = mocker.Mock()
    from src.stt import SpeechListener
    listener = SpeechListener("condensor", on_wake=on_wake)
    gen = listener.listen_for_commands()
    result = next(gen)
    assert result == "play music"
    on_wake.assert_called_once()


def test_speech_listener_on_wake_exception_does_not_crash(mocker):
    """on_wake raising should not terminate the generator — Phase 2 still runs."""
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")

    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.side_effect = [
        "condensor",    # Phase 1: wake word only
        "play music",   # Phase 2: query
    ]

    on_wake = mocker.Mock(side_effect=RuntimeError("TTS subprocess died"))
    from src.stt import SpeechListener
    listener = SpeechListener("condensor", on_wake=on_wake)
    gen = listener.listen_for_commands()
    result = next(gen)
    assert result == "play music"
    on_wake.assert_called_once()


# --- listen_once ---

def test_listen_once_returns_text_when_speech_detected(mocker):
    """listen_once returns recognized text when the user speaks within the timeout."""
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")
    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.return_value = "turn off the lights"

    from src.stt import SpeechListener
    listener = SpeechListener("condensor")
    result = listener.listen_once(timeout=5)

    assert result == "turn off the lights"


def test_listen_once_returns_none_on_timeout(mocker):
    """listen_once returns None when no speech is detected within the timeout."""
    import speech_recognition as sr
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")
    mock_r = mock_recognizer.return_value
    mock_r.listen.side_effect = sr.WaitTimeoutError()

    from src.stt import SpeechListener
    listener = SpeechListener("condensor")
    result = listener.listen_once(timeout=5)

    assert result is None


def test_listen_once_returns_none_on_unrecognized_speech(mocker):
    """listen_once returns None when speech is heard but cannot be recognized."""
    import speech_recognition as sr
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")
    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.side_effect = sr.UnknownValueError()

    from src.stt import SpeechListener
    listener = SpeechListener("condensor")
    result = listener.listen_once(timeout=5)

    assert result is None
