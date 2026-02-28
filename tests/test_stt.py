def test_extract_query_finds_keyword():
    from src.stt import extract_query
    result = extract_query("condensor tell me about mars", "condensor")
    assert result == "tell me about mars"


def test_extract_query_case_insensitive():
    from src.stt import extract_query
    result = extract_query("Condensor How far is Chicago", "condensor")
    assert result == "how far is chicago"


def test_extract_query_returns_none_when_missing():
    from src.stt import extract_query
    result = extract_query("tell me about mars", "condensor")
    assert result is None


def test_extract_query_returns_none_when_nothing_after_keyword():
    from src.stt import extract_query
    result = extract_query("condensor", "condensor")
    assert result is None


def test_speech_listener_yields_query(mocker):
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mock_mic = mocker.patch("src.stt.sr.Microphone")

    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.side_effect = [
        "hello there",           # not a wake word — skip
        "condensor play music",  # wake word — yield query
        StopIteration,
    ]

    from src.stt import SpeechListener
    listener = SpeechListener("condensor")
    gen = listener.listen_for_commands()
    result = next(gen)
    assert result == "play music"
