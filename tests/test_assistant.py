def test_build_system_prompt_includes_location_and_devices():
    from src.assistant import build_system_prompt
    prompt = build_system_prompt(
        {"city": "Chicago", "region": "Illinois", "timezone": "America/Chicago"},
        [{"name": "Living Room Light"}, {"name": "Bedroom Fan"}]
    )
    assert "Chicago" in prompt
    assert "Living Room Light" in prompt
    assert "Bedroom Fan" in prompt


def _make_assistant(mocker, listener_queries, listen_once_returns):
    """Helper: build a fully-mocked Assistant for run() tests."""
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    })
    mock_tts = mocker.MagicMock()
    mocker.patch("src.assistant.TTSEngine", return_value=mock_tts)
    mock_ai = mocker.MagicMock()
    mock_ai.ask.return_value = "I'll handle that."
    mocker.patch("src.assistant.AIClient", return_value=mock_ai)
    mock_listener = mocker.MagicMock()
    mock_listener.wake_word = "compressor"
    mock_listener.listen_for_commands.return_value = iter(listener_queries)
    mock_listener.listen_once.side_effect = list(listen_once_returns)
    mocker.patch("src.assistant.SpeechListener", return_value=mock_listener)
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")

    from src.assistant import Assistant
    return Assistant(), mock_ai, mock_listener


def test_run_calls_ask_for_follow_up_in_same_thread(mocker):
    """Follow-up speech within the timeout stays in the same Claude conversation thread."""
    assistant, mock_ai, _ = _make_assistant(
        mocker,
        listener_queries=["turn on the lights"],
        listen_once_returns=["what about the bedroom?", None],
    )
    assistant.run()

    assert mock_ai.ask.call_count == 2
    assert mock_ai.ask.call_args_list[0][0][0] == "turn on the lights"
    assert mock_ai.ask.call_args_list[1][0][0] == "what about the bedroom?"


def test_run_resets_ai_after_conversation_ends(mocker):
    """When listen_once times out, ai.reset() is called to clear the thread context."""
    assistant, mock_ai, _ = _make_assistant(
        mocker,
        listener_queries=["turn on the lights"],
        listen_once_returns=[None],
    )
    assistant.run()

    mock_ai.reset.assert_called_once()


def test_run_prints_listening_message_after_conversation_ends(mocker, capsys):
    """After a conversation thread ends, a 'Listening for wake word' line is printed."""
    assistant, _, _ = _make_assistant(
        mocker,
        listener_queries=["turn on the lights"],
        listen_once_returns=[None],
    )
    assistant.run()

    captured = capsys.readouterr()
    assert "Listening for wake word" in captured.out


def test_assistant_passes_on_wake_to_listener(mocker):
    """Assistant wires tts.speak('Yes?') as the on_wake callback."""
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    })
    mock_tts_instance = mocker.MagicMock()
    mocker.patch("src.assistant.TTSEngine", return_value=mock_tts_instance)
    mock_listener_cls = mocker.patch("src.assistant.SpeechListener")
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.AIClient")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")

    from src.assistant import Assistant
    Assistant()

    call_kwargs = mock_listener_cls.call_args
    assert "on_wake" in call_kwargs.kwargs
    # Trigger the callback and confirm it calls tts.speak("Yes?")
    call_kwargs.kwargs["on_wake"]()
    mock_tts_instance.speak.assert_called_once_with("Yes?")
