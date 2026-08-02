def test_extract_query_finds_keyword():
    from src.stt import extract_query
    result = extract_query("compressor tell me about mars", "compressor")
    assert result == "tell me about mars"


def test_extract_query_case_insensitive():
    from src.stt import extract_query
    result = extract_query("Compressor How far is Chicago", "compressor")
    assert result == "How far is Chicago"


def test_extract_query_returns_none_when_missing():
    from src.stt import extract_query
    result = extract_query("tell me about mars", "compressor")
    assert result is None


def test_extract_query_returns_none_when_nothing_after_keyword():
    from src.stt import extract_query
    result = extract_query("compressor", "compressor")
    assert result is None


def test_speech_listener_yields_inline_query(mocker):
    """Wake word + query in same phrase → yield query directly, no on_wake call."""
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")

    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.return_value = "compressor play music"

    on_wake = mocker.Mock()
    from src.stt import SpeechListener
    listener = SpeechListener("compressor", on_wake=on_wake)
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
        "compressor",    # Phase 1: wake word only
        "play music",   # Phase 2: query
    ]

    on_wake = mocker.Mock()
    from src.stt import SpeechListener
    listener = SpeechListener("compressor", on_wake=on_wake)
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
        "compressor",    # Phase 1: wake word only
        "play music",   # Phase 2: query
    ]

    on_wake = mocker.Mock(side_effect=RuntimeError("TTS subprocess died"))
    from src.stt import SpeechListener
    listener = SpeechListener("compressor", on_wake=on_wake)
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
    listener = SpeechListener("compressor")
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
    listener = SpeechListener("compressor")
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
    listener = SpeechListener("compressor")
    result = listener.listen_once(timeout=5)

    assert result is None


# --- openWakeWord Phase 1 (used when models/compressor.onnx exists) ---

def _mock_oww(mocker, predict_scores, listen_once_returns):
    """Patch the openWakeWord model, pyaudio stream, and listen_once for streaming-path tests."""
    mocker.patch("src.stt.os.path.exists", return_value=True)
    mock_model_cls = mocker.patch("src.stt._OWWModel")
    mock_model = mock_model_cls.return_value
    mock_model.predict.side_effect = predict_scores
    mock_pa = mocker.patch("src.stt.pyaudio.PyAudio")
    stream = mock_pa.return_value.open.return_value
    stream.read.return_value = b"\x00" * 2560  # 1280 int16 samples
    mock_listen_once = mocker.patch(
        "src.stt.SpeechListener.listen_once", side_effect=list(listen_once_returns)
    )
    return mock_model, stream, mock_listen_once


def test_oww_detection_above_threshold_yields_inline_query(mocker):
    """Score >= threshold -> capture speech; inline remainder yielded without on_wake."""
    on_wake = mocker.Mock()
    _mock_oww(mocker, [{"compressor": 0.9}], ["turn on the lights"])

    from src.stt import SpeechListener
    listener = SpeechListener("compressor", on_wake=on_wake, wake_threshold=0.5)
    gen = listener.listen_for_commands()
    assert next(gen) == "turn on the lights"
    on_wake.assert_not_called()


def test_oww_below_threshold_keeps_streaming(mocker):
    """Frames below threshold are ignored; detection fires on the first frame at/above it."""
    mock_model, stream, _ = _mock_oww(
        mocker,
        [{"compressor": 0.1}, {"compressor": 0.2}, {"compressor": 0.8}],
        ["play music"],
    )

    from src.stt import SpeechListener
    listener = SpeechListener("compressor", wake_threshold=0.5)
    gen = listener.listen_for_commands()
    assert next(gen) == "play music"
    assert mock_model.predict.call_count == 3


def test_oww_wake_alone_calls_on_wake_then_phase2(mocker):
    """Silence after detection -> on_wake fires ('Yes?'), then Phase 2 captures the query."""
    on_wake = mocker.Mock()
    _mock_oww(mocker, [{"compressor": 0.9}], [None, "play music"])

    from src.stt import SpeechListener
    listener = SpeechListener("compressor", on_wake=on_wake, wake_threshold=0.5)
    gen = listener.listen_for_commands()
    assert next(gen) == "play music"
    on_wake.assert_called_once()


def test_oww_strips_wake_word_from_inline_capture(mocker):
    """If the captured text still contains the wake word, only the query part is yielded."""
    _mock_oww(mocker, [{"compressor": 0.9}], ["compressor turn on the lights"])

    from src.stt import SpeechListener
    listener = SpeechListener("compressor", wake_threshold=0.5)
    gen = listener.listen_for_commands()
    assert next(gen) == "turn on the lights"


def test_falls_back_to_google_stt_when_model_file_missing(mocker):
    """No .onnx file -> existing cloud-STT wake detection is used, unchanged."""
    mocker.patch("src.stt.os.path.exists", return_value=False)
    mock_recognizer = mocker.patch("src.stt.sr.Recognizer")
    mocker.patch("src.stt.sr.Microphone")
    mock_r = mock_recognizer.return_value
    mock_r.listen.return_value = mocker.Mock()
    mock_r.recognize_google.return_value = "compressor play music"

    from src.stt import SpeechListener
    listener = SpeechListener("compressor")
    gen = listener.listen_for_commands()
    assert next(gen) == "play music"
