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
    mocker.patch("src.assistant.action_log.configure")

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
    mocker.patch("src.assistant.action_log.configure")

    from src.assistant import Assistant
    Assistant()

    call_kwargs = mock_listener_cls.call_args
    assert "on_wake" in call_kwargs.kwargs
    # Trigger the callback and confirm it calls tts.speak("Yes?")
    call_kwargs.kwargs["on_wake"]()
    mock_tts_instance.speak.assert_called_once_with("Yes?")


def _follower_config(**overrides):
    config = {
        "wake_word": "compressor",
        "role": "follower",
        "host_ip": "192.168.1.50",
        "host_port": 8765,
        "unit_name": "Kitchen",
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    }
    config.update(overrides)
    return config


def _make_follower_assistant(mocker, listener_queries, listen_once_returns, network_query_return="Handled."):
    mocker.patch("src.assistant.load_config", return_value=_follower_config())
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mock_listener = mocker.MagicMock()
    mock_listener.wake_word = "compressor"
    mock_listener.listen_for_commands.return_value = iter(listener_queries)
    mock_listener.listen_once.side_effect = list(listen_once_returns)
    mocker.patch("src.assistant.SpeechListener", return_value=mock_listener)

    mock_network_cls = mocker.patch("src.assistant.NetworkClient")
    mock_network = mock_network_cls.return_value
    mock_network.get_info.return_value = {}
    mock_network.query.return_value = network_query_return

    mock_ai_cls = mocker.patch("src.assistant.AIClient")
    mock_tuya_cls = mocker.patch("src.assistant.TuyaController")
    mock_spotify_cls = mocker.patch("src.assistant.SpotifyController")
    mock_scheduler_cls = mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")

    from src.assistant import Assistant
    assistant = Assistant()
    return assistant, mock_ai_cls, mock_tuya_cls, mock_spotify_cls, mock_scheduler_cls, mock_network


def test_follower_never_constructs_ai_tuya_spotify_scheduler(mocker):
    assistant, mock_ai_cls, mock_tuya_cls, mock_spotify_cls, mock_scheduler_cls, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    mock_ai_cls.assert_not_called()
    mock_tuya_cls.assert_not_called()
    mock_spotify_cls.assert_not_called()
    mock_scheduler_cls.assert_not_called()
    assert assistant._ai_clients == {}
    assert assistant._tuya is None
    assert assistant._spotify is None
    assert assistant._scheduler is None


def test_follower_run_delegates_query_to_network(mocker):
    assistant, _, _, _, _, mock_network = _make_follower_assistant(
        mocker,
        listener_queries=["turn on the lights"],
        listen_once_returns=[None],
        network_query_return="Living Room Light turned on.",
    )
    assistant.run()

    mock_network.query.assert_called_once_with("Kitchen", "turn on the lights")


def test_host_isolates_conversations_per_unit(mocker):
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")

    mock_ai_cls = mocker.patch("src.assistant.AIClient")
    mock_ai_cls.side_effect = lambda *a, **k: mocker.MagicMock()

    from src.assistant import Assistant
    assistant = Assistant()

    client_a = assistant._get_ai_client("Kitchen")
    client_b = assistant._get_ai_client("Living Room")
    client_a_again = assistant._get_ai_client("Kitchen")

    assert client_a is not client_b
    assert client_a is client_a_again
    assert mock_ai_cls.call_count == 2


def test_query_handler_wired_only_after_host_state_ready(mocker):
    """app.state.query_handler must not be set until all host-only state
    (tuya/spotify/scheduler/system_prompt) is fully constructed, and the
    background server thread must not be handed a handler that could touch
    that state early — this was the fix for a race where a follower query
    landing during startup would permanently poison that unit's AIClient
    with system_prompt=None."""
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.NetworkClient")
    mock_thread_cls = mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.AIClient")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")

    from src.assistant import Assistant, app
    app.state.query_handler = None  # reset in case a prior test left it set

    assistant = Assistant()

    thread_kwargs = mock_thread_cls.call_args.kwargs["kwargs"]
    assert "query_handler" not in thread_kwargs

    assert app.state.query_handler == assistant._process_query


def test_process_query_holds_unit_lock_during_ai_ask(mocker):
    """_process_query must hold the per-unit lock for the whole ai.ask() call
    so two concurrent requests for the same unit can't interleave writes to
    the same AIClient's message history."""
    assistant, mock_ai, _ = _make_assistant(mocker, listener_queries=[], listen_once_returns=[])

    lock = assistant._get_unit_lock("host")

    def check_locked_and_answer(*args, **kwargs):
        assert lock.locked()
        return "ok"

    mock_ai.ask.side_effect = check_locked_and_answer

    result = assistant._process_query("host", "hello")

    assert result == "ok"
    assert not lock.locked()


def test_get_unit_lock_returns_same_lock_per_unit(mocker):
    assistant, _, _ = _make_assistant(mocker, listener_queries=[], listen_once_returns=[])

    lock_a = assistant._get_unit_lock("Kitchen")
    lock_a_again = assistant._get_unit_lock("Kitchen")
    lock_b = assistant._get_unit_lock("Living Room")

    assert lock_a is lock_a_again
    assert lock_a is not lock_b


def test_process_query_logs_query_and_response(mocker):
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")
    mock_log_query = mocker.patch("src.assistant.action_log.log_query")
    mock_log_response = mocker.patch("src.assistant.action_log.log_response")

    mock_ai = mocker.MagicMock()
    mock_ai.ask.return_value = "Living Room Light turned on."
    mocker.patch("src.assistant.AIClient", return_value=mock_ai)

    from src.assistant import Assistant
    assistant = Assistant()
    result = assistant._process_query("host", "turn on the living room light")

    assert result == "Living Room Light turned on."
    mock_log_query.assert_called_once_with("host", "turn on the living room light")
    mock_log_response.assert_called_once_with("host", "Living Room Light turned on.")


def test_assistant_passes_wake_model_config_to_listener(mocker):
    """wake_model_path / wake_threshold from config.yaml reach SpeechListener."""
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "wake_model_path": "models/custom.onnx",
        "wake_threshold": 0.7,
        "tuya": {},
        "spotify": {},
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mock_listener_cls = mocker.patch("src.assistant.SpeechListener")
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.AIClient")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")

    from src.assistant import Assistant
    Assistant()

    kwargs = mock_listener_cls.call_args.kwargs
    assert kwargs["wake_model_path"] == "models/custom.onnx"
    assert kwargs["wake_threshold"] == 0.7


def test_tool_exception_aborts_query_with_generic_apology(mocker):
    """A crashing tool propagates out of _tool_handler; _process_query catches it."""
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "role": "host",
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")
    mock_log_error = mocker.patch("src.assistant.action_log.log_error")

    mock_ai = mocker.MagicMock()
    # ai.ask invokes the tool handler it's given, which raises; the exception
    # must escape ask() and be caught by _process_query.
    def ask(text, handler):
        return handler("control_tuya_device", {"device_name": "Lamp", "action": "on"})
    mock_ai.ask.side_effect = ask
    mocker.patch("src.assistant.AIClient", return_value=mock_ai)
    mocker.patch.dict("src.assistant.ACTIONS", {"control_tuya_device": mocker.Mock(side_effect=RuntimeError("boom"))})

    from src.assistant import Assistant
    assistant = Assistant()
    result = assistant._process_query("host", "turn on the lamp")

    assert result == "Sorry, something went wrong."
    mock_log_error.assert_called_once_with("host", "ai_ask", "boom")


def test_network_open_program_for_this_unit_launches(mocker):
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    assistant._launcher = mocker.MagicMock()

    assistant._handle_network_command({
        "type": "open_program", "target_unit": "Kitchen",
        "program": "brave", "process": "youtube", "argument": "https://youtube.com",
    })

    assistant._launcher.open.assert_called_once_with(
        "brave", process="youtube", argument="https://youtube.com"
    )


def test_network_open_program_for_other_unit_ignored(mocker):
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    assistant._launcher = mocker.MagicMock()

    assistant._handle_network_command({
        "type": "open_program", "target_unit": "Bedroom",
        "program": "brave", "process": None, "argument": None,
    })

    assistant._launcher.open.assert_not_called()


def test_network_spotify_app_start_and_stop_run_on_any_unit(mocker):
    """spotify_app broadcasts are OS-level and need no Spotify credentials,
    so a follower (which has no SpotifyController) must still act on them."""
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    mock_app = mocker.patch("src.assistant.spotify_app")

    assistant._handle_network_command({"type": "spotify_app", "action": "start"})
    mock_app.start.assert_called_once()
    mock_app.stop.assert_not_called()

    assistant._handle_network_command({"type": "spotify_app", "action": "stop"})
    mock_app.stop.assert_called_once()


def test_network_open_url_for_this_unit_opens_browser(mocker):
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    assistant._launcher = mocker.MagicMock()

    assistant._handle_network_command({
        "type": "open_url", "target_unit": "Kitchen", "url": "https://www.youtube.com/watch?v=x",
    })

    assistant._launcher.open.assert_called_once_with(
        "browser", argument="https://www.youtube.com/watch?v=x"
    )


def test_network_open_url_without_target_opens_on_every_unit(mocker):
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    assistant._launcher = mocker.MagicMock()

    assistant._handle_network_command({
        "type": "open_url", "target_unit": None, "url": "https://www.youtube.com/watch?v=x",
    })

    assistant._launcher.open.assert_called_once_with(
        "browser", argument="https://www.youtube.com/watch?v=x"
    )


def test_network_open_url_for_other_unit_ignored(mocker):
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    assistant._launcher = mocker.MagicMock()

    assistant._handle_network_command({
        "type": "open_url", "target_unit": "Bedroom", "url": "https://www.youtube.com/watch?v=x",
    })

    assistant._launcher.open.assert_not_called()


def test_follower_constructs_program_launcher(mocker):
    """ProgramLauncher must exist on ALL roles — followers execute remote launches locally."""
    mock_launcher_cls = mocker.patch("src.assistant.ProgramLauncher")
    assistant, _, _, _, _, _ = _make_follower_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    mock_launcher_cls.assert_called_once()
    assert assistant._launcher is mock_launcher_cls.return_value
    assert mock_launcher_cls.call_args.kwargs.get("unit_name") == "Kitchen"


def test_build_system_prompt_includes_program_tree():
    from src.assistant import build_system_prompt
    prompt = build_system_prompt(
        {"city": "Chicago", "region": "Illinois", "timezone": "America/Chicago"},
        [],
        [
            {"name": "brave", "launch": "brave", "process_name": "brave",
             "aliases": ["browser"], "processes": {"youtube": "https://youtube.com"}},
            {"name": "notepad", "launch": "notepad", "process_name": "notepad"},
        ],
    )
    assert "brave" in prompt
    assert "browser" in prompt      # alias listed
    assert "youtube" in prompt      # known process listed
    assert "notepad" in prompt


def test_build_system_prompt_skips_nameless_program_entry():
    from src.assistant import build_system_prompt
    # Must not raise on a malformed entry missing "name".
    build_system_prompt({}, [], [{"launch": "x"}])


def test_tool_handler_routes_requester_and_host_names_into_action_context(mocker):
    """Regression test for the ActionContext wiring in _tool_handler: a
    request from a unit other than the host must take the optimistic
    broadcast path (network.broadcast), not the local-launch path
    (launcher.open). This fails if unit_name/host_unit_name are swapped
    when constructing ActionContext."""
    assistant, mock_ai, _ = _make_assistant(mocker, listener_queries=[], listen_once_returns=[])
    assistant._launcher = mocker.MagicMock()

    result = assistant._tool_handler("Kitchen", "open_program", {"program": "brave"})

    assistant._network.broadcast.assert_called_once()
    payload = assistant._network.broadcast.call_args[0][0]
    assert payload["target_unit"] == "Kitchen"
    assistant._launcher.open.assert_not_called()
    assert "Kitchen" in result


# --- Claude mode ---

CODING_AGENT_CFG = {
    "agent": "claude_code",
    "default_workdir": "C:\\git\\compressor",
    "workdirs": {"jldesigns": "C:\\git\\jldesigns"},
}


def _make_claude_mode_assistant(mocker, listener_queries, listen_once_returns, coding_agent=True, role="host"):
    """Host (or follower) assistant with a mocked coding-agent session factory."""
    config = {
        "wake_word": "compressor",
        "role": role,
        "host_port": 8765,
        "anthropic_api_key": "test-key",
        "tuya": {},
        "spotify": {},
    }
    if role == "follower":
        config["host_ip"] = "192.168.1.50"
        config["unit_name"] = "Kitchen"
    if coding_agent:
        config["coding_agent"] = dict(CODING_AGENT_CFG)
    mocker.patch("src.assistant.load_config", return_value=config)
    mock_tts = mocker.MagicMock()
    mocker.patch("src.assistant.TTSEngine", return_value=mock_tts)
    mock_listener = mocker.MagicMock()
    mock_listener.wake_word = "compressor"
    mock_listener.listen_for_commands.return_value = iter(listener_queries)
    mock_listener.listen_once.side_effect = list(listen_once_returns)
    mocker.patch("src.assistant.SpeechListener", return_value=mock_listener)
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    # threading.Thread stays REAL here: Claude mode runs its task worker on a
    # thread, and the host-server thread just calls the mocked run_server.
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.AIClient")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")

    mock_session = mocker.MagicMock()
    mock_session.send.return_value = "Task complete."
    mock_factory = mocker.patch("src.assistant.create_session", return_value=mock_session)

    from src.assistant import Assistant
    return Assistant(), mock_session, mock_factory, mock_tts


def test_parse_claude_mode_entry_variants(mocker):
    assistant, _, _, _ = _make_claude_mode_assistant(mocker, [], [])
    assert assistant._parse_claude_mode_entry("start claude") == ""
    assert assistant._parse_claude_mode_entry("Start Claude Code") == ""
    assert assistant._parse_claude_mode_entry("start claude in jldesigns") == "jldesigns"
    assert assistant._parse_claude_mode_entry("start claude code in my site") == "my site"
    assert assistant._parse_claude_mode_entry("restart claude") is None
    assert assistant._parse_claude_mode_entry("turn on the lights") is None


def test_start_claude_enters_mode_and_routes_speech_to_session(mocker):
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["add a dark mode toggle", "compressor"],
    )
    assistant.run()

    mock_factory.assert_called_once()
    mock_session.start.assert_called_once_with("C:\\git\\compressor")
    mock_session.send.assert_called_once_with("add a dark mode toggle")
    mock_tts.speak.assert_any_call("Task complete.")


def test_wake_word_alone_exits_mode(mocker):
    assistant, mock_session, _, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["compressor"],
    )
    assistant.run()

    mock_session.send.assert_not_called()
    mock_session.stop.assert_called_once()
    mock_tts.speak.assert_any_call("Compressor ready.")


def test_wake_word_with_punctuation_still_exits(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["Compressor."],
    )
    assistant.run()

    mock_session.send.assert_not_called()
    mock_session.stop.assert_called_once()


def test_wake_word_embedded_in_sentence_is_forwarded_not_exit(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["add a test to compressor's launcher", "compressor"],
    )
    assistant.run()

    mock_session.send.assert_called_once_with("add a test to compressor's launcher")


def test_start_claude_in_named_project_uses_configured_workdir(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude in jldesigns"],
        listen_once_returns=["compressor"],
    )
    assistant.run()

    mock_session.start.assert_called_once_with("C:\\git\\jldesigns")


def test_start_claude_unknown_project_refuses_without_entering_mode(mocker):
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude in narnia"],
        listen_once_returns=[],
    )
    assistant.run()

    mock_factory.assert_not_called()
    mock_session.start.assert_not_called()
    assert any("narnia" in str(c) for c in mock_tts.speak.call_args_list)


def test_start_claude_without_config_refuses(mocker):
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=[],
        coding_agent=False,
    )
    assistant.run()

    mock_factory.assert_not_called()
    assert any("isn't configured" in str(c) for c in mock_tts.speak.call_args_list)


def test_mode_utterances_never_reach_normal_ai(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["what is 2 plus 2", "compressor"],
    )
    mock_process = mocker.patch.object(assistant, "_process_query")
    assistant.run()

    mock_process.assert_not_called()
    mock_session.send.assert_called_once_with("what is 2 plus 2")


def test_follower_role_gets_claude_mode_without_host_logging(mocker):
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["compressor"],
        role="follower",
    )
    mock_log_claude_mode = mocker.patch("src.assistant.action_log.log_claude_mode")

    assistant.run()

    mock_factory.assert_called_once()
    mock_session.start.assert_called_once_with("C:\\git\\compressor")
    mock_session.stop.assert_called_once()
    mock_tts.speak.assert_any_call("Compressor ready.")
    mock_log_claude_mode.assert_not_called()


def test_claude_mode_factory_error_does_not_crash_process(mocker):
    """A malformed coding_agent config (e.g. int(None) TypeError from a
    blank max_turns in YAML) must degrade to speech, not propagate out of
    run() and kill the whole assistant process."""
    assistant, mock_session, mock_factory, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=[],
    )
    mock_factory.side_effect = TypeError("boom")

    assistant.run()  # must not raise

    mock_tts.speak.assert_any_call("Claude mode hit an error.")
    mock_tts.speak.assert_any_call("Compressor ready.")
    mock_session.stop.assert_not_called()  # session was never created


def test_remote_query_cannot_enter_claude_mode(mocker):
    """'start claude' arriving via _process_query (i.e. from a remote
    follower's /query call) must never reach the Claude-mode entry check —
    that parsing only happens in run()'s local wake-word loop. It should
    flow straight to the normal AI conversation path instead."""
    assistant, _, mock_factory, _ = _make_claude_mode_assistant(
        mocker, listener_queries=[], listen_once_returns=[]
    )
    mock_ai = mocker.MagicMock()
    mock_ai.ask.return_value = "handled normally"
    mocker.patch.object(assistant, "_get_ai_client", return_value=mock_ai)

    result = assistant._process_query("Kitchen", "start claude")

    mock_factory.assert_not_called()
    mock_ai.ask.assert_called_once()
    assert result == "handled normally"


def test_claude_mode_idle_timeout_exits_and_speaks(mocker):
    """Continuous silence past CLAUDE_MODE_IDLE_EXIT_SECONDS (patched to 0 so
    the very first silent listen is already past the deadline) auto-exits the
    mode, stops the session, and speaks a timeout message."""
    assistant, mock_session, _, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=[None],
    )
    mocker.patch("src.assistant.CLAUDE_MODE_IDLE_EXIT_SECONDS", 0)

    assistant.run()

    mock_session.stop.assert_called_once()
    mock_tts.speak.assert_any_call("Claude mode timed out.")


def test_follow_up_while_task_running_is_queued_and_both_responses_spoken(mocker):
    """A second utterance arriving while a task is still running gets 'Queued.'
    feedback, and both responses are spoken once the tasks finish — the mode
    no longer blocks the voice loop on session.send()."""
    import threading as _threading

    gate = _threading.Event()
    responses = {"task one": "First done.", "task two": "Second done."}

    assistant, mock_session, _, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=[],
    )
    mock_session.send.side_effect = lambda text: (gate.wait(timeout=5), responses[text])[1]

    listens = iter(["task one", "task two", "exit-now"])

    def scripted_listen(**kwargs):
        value = next(listens)
        if value == "exit-now":
            gate.set()  # let the worker finish before the exit drain
            return "compressor"
        return value

    assistant._listener.listen_once.side_effect = scripted_listen

    assistant.run()

    assert mock_session.send.call_count == 2
    mock_tts.speak.assert_any_call("Working on it.")
    mock_tts.speak.assert_any_call("Queued.")
    mock_tts.speak.assert_any_call("First done.")
    mock_tts.speak.assert_any_call("Second done.")


def test_exit_while_task_running_cancels_and_discards_result(mocker):
    """Wake word alone while a task is in flight cancels the session's work;
    the cancelled task's empty response is discarded, never spoken."""
    import threading as _threading

    gate = _threading.Event()

    assistant, mock_session, _, mock_tts = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["long task", "compressor"],
    )
    mock_session.send.side_effect = lambda text: (gate.wait(timeout=5), "")[1]
    mock_session.cancel.side_effect = gate.set

    assistant.run()

    mock_session.cancel.assert_called()
    mock_session.stop.assert_called_once()
    assert mocker.call("") not in mock_tts.speak.call_args_list
    mock_tts.speak.assert_any_call("Compressor ready.")


def test_mode_exchange_and_lifecycle_are_action_logged(mocker):
    assistant, mock_session, _, _ = _make_claude_mode_assistant(
        mocker,
        listener_queries=["start claude"],
        listen_once_returns=["do a thing", "compressor"],
    )
    mock_log_claude_mode = mocker.patch("src.assistant.action_log.log_claude_mode")

    assistant.run()

    mode_events = [call.args[1] for call in mock_log_claude_mode.call_args_list]
    assert mode_events == ["enter", "exchange", "exit"]
    assert mock_log_claude_mode.call_args_list[0].args[0] == "host"
    assert mock_log_claude_mode.call_args_list[1].args[2] == "do a thing -> Task complete."
