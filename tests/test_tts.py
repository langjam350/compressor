import pytest


def _make_mock_proc(mocker, *, readline_side_effect=None, poll_return=None):
    """Helper: build a Popen mock with sensible TTS defaults."""
    mock_proc = mocker.MagicMock()
    mock_proc.poll.return_value = poll_return  # None = still alive
    if readline_side_effect is not None:
        mock_proc.stdout.readline.side_effect = readline_side_effect
    return mock_proc


def test_speak_sends_text_to_subprocess(mocker):
    mock_proc = _make_mock_proc(mocker, readline_side_effect=["READY\n", "DONE\n"])
    mocker.patch("src.tts.subprocess.Popen", return_value=mock_proc)

    from src.tts import TTSEngine
    tts = TTSEngine()
    tts.speak("hello world")

    mock_proc.stdin.write.assert_called_once_with("hello world\n")
    mock_proc.stdin.flush.assert_called_once()
    assert mock_proc.stdout.readline.call_count == 2  # READY + DONE


def test_speak_empty_string_does_nothing(mocker):
    mock_proc = _make_mock_proc(mocker, readline_side_effect=["READY\n"])
    mocker.patch("src.tts.subprocess.Popen", return_value=mock_proc)

    from src.tts import TTSEngine
    tts = TTSEngine()
    tts.speak("")

    mock_proc.stdin.write.assert_not_called()
    assert mock_proc.stdout.readline.call_count == 1  # only the READY handshake


def test_init_raises_if_worker_fails_to_start(mocker):
    mock_proc = _make_mock_proc(mocker, readline_side_effect=[""])  # EOF = crash
    mock_proc.returncode = 1
    mocker.patch("src.tts.subprocess.Popen", return_value=mock_proc)

    from src.tts import TTSEngine
    with pytest.raises(RuntimeError, match="TTS worker failed to initialize"):
        TTSEngine()


def test_speak_raises_if_subprocess_already_dead(mocker):
    mock_proc = _make_mock_proc(
        mocker,
        readline_side_effect=["READY\n"],
        poll_return=1,  # process has exited
    )
    mock_proc.returncode = 1
    mocker.patch("src.tts.subprocess.Popen", return_value=mock_proc)

    from src.tts import TTSEngine
    tts = TTSEngine()
    with pytest.raises(RuntimeError, match="TTS subprocess has exited"):
        tts.speak("hello")


def test_speak_raises_if_subprocess_dies_mid_speech(mocker):
    mock_proc = _make_mock_proc(
        mocker,
        readline_side_effect=["READY\n", ""],  # empty = EOF during speech
    )
    mock_proc.poll.return_value = None  # alive when we check, dies on readline
    mock_proc.returncode = -1
    mocker.patch("src.tts.subprocess.Popen", return_value=mock_proc)

    from src.tts import TTSEngine
    tts = TTSEngine()
    with pytest.raises(RuntimeError, match="TTS subprocess died during speech"):
        tts.speak("hello")
