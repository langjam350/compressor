import json
import threading
import time


def _stream_lines(result_text="Done.", session_id="sess-123", tool_uses=None, include_result=True):
    """Build the stdout lines a `claude -p --output-format stream-json` run emits."""
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": session_id})]
    for name, tool_input in tool_uses or []:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]},
        }))
    if include_result:
        lines.append(json.dumps({
            "type": "result", "subtype": "success",
            "result": result_text, "session_id": session_id,
        }))
    return [line + "\n" for line in lines]


class _FakeProc:
    def __init__(self, lines=None, returncode=0):
        self.stdout = iter(lines or [])
        self.returncode = returncode
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True


def _patch_popen(mocker, proc):
    return mocker.patch(
        "src.integrations.coding_agents.claude_code.subprocess.Popen",
        return_value=proc,
    )


def _patch_cli(mocker, path="C:\\npm\\claude.cmd"):
    return mocker.patch(
        "src.integrations.coding_agents.claude_code.shutil.which", return_value=path
    )


def _make_session(**kwargs):
    from src.integrations.coding_agents.claude_code import ClaudeCodeSession
    session = ClaudeCodeSession(**kwargs)
    session.start("C:\\proj")
    return session


def test_factory_builds_claude_code_backend():
    from src.integrations.coding_agents import create_session
    from src.integrations.coding_agents.claude_code import ClaudeCodeSession
    session = create_session({"agent": "claude_code", "model": "claude-sonnet-5",
                              "permission_mode": "plan", "max_turns": 10,
                              "task_timeout_seconds": 120})
    assert isinstance(session, ClaudeCodeSession)


def test_factory_defaults_agent_to_claude_code():
    from src.integrations.coding_agents import create_session
    from src.integrations.coding_agents.claude_code import ClaudeCodeSession
    assert isinstance(create_session({}), ClaudeCodeSession)


def test_factory_downgrades_bypass_permissions(mocker, capsys):
    """permission_mode: bypassPermissions must never reach the CLI — it's
    silently downgraded to acceptEdits so config alone can't defeat the
    documented permission rail."""
    from src.integrations.coding_agents import create_session

    _patch_cli(mocker)
    mock_popen = _patch_popen(mocker, _FakeProc(_stream_lines()))

    session = create_session({"agent": "claude_code", "permission_mode": "bypassPermissions"})
    session.start("C:\\proj")
    session.send("do something")

    cmd = mock_popen.call_args.args[0]
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "acceptEdits"
    assert "not allowed" in capsys.readouterr().out


def test_factory_unknown_agent_returns_stub_with_spoken_message():
    from src.integrations.coding_agents import create_session
    session = create_session({"agent": "gemini_cli"})
    session.start("C:\\proj")
    result = session.send("do something")
    assert result == "Coding agent 'gemini_cli' isn't supported on this unit."
    session.cancel()  # must not raise
    session.stop()    # must not raise


def test_send_builds_expected_first_command(mocker):
    _patch_cli(mocker)
    mock_popen = _patch_popen(mocker, _FakeProc(_stream_lines()))

    session = _make_session()
    result = session.send("add a button")

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "C:\\npm\\claude.cmd"
    assert cmd[1:3] == ["-p", "add a button"]
    assert "--resume" not in cmd
    assert "--model" not in cmd  # unset -> omitted
    assert ["--output-format", "stream-json"] == cmd[cmd.index("--output-format"):cmd.index("--output-format") + 2]
    assert "--verbose" in cmd  # the CLI requires it for stream-json with -p
    assert ["--permission-mode", "acceptEdits"] == cmd[cmd.index("--permission-mode"):cmd.index("--permission-mode") + 2]
    assert ["--add-dir", "C:\\proj"] == cmd[cmd.index("--add-dir"):cmd.index("--add-dir") + 2]
    assert ["--max-turns", "25"] == cmd[cmd.index("--max-turns"):cmd.index("--max-turns") + 2]
    assert "--append-system-prompt" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert mock_popen.call_args.kwargs["cwd"] == "C:\\proj"
    assert result == "Done."


def test_second_send_resumes_captured_session_id(mocker):
    _patch_cli(mocker)
    mock_popen = _patch_popen(mocker, _FakeProc(_stream_lines(session_id="sess-abc")))
    mock_popen.side_effect = lambda *a, **k: _FakeProc(_stream_lines(session_id="sess-abc"))

    session = _make_session()
    session.send("first")
    session.send("second")

    second_cmd = mock_popen.call_args_list[1].args[0]
    idx = second_cmd.index("--resume")
    assert second_cmd[idx + 1] == "sess-abc"


def test_model_flag_present_only_when_configured(mocker):
    _patch_cli(mocker)
    mock_popen = _patch_popen(mocker, _FakeProc(_stream_lines()))

    session = _make_session(model="claude-sonnet-5")
    session.send("hello")

    cmd = mock_popen.call_args.args[0]
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "claude-sonnet-5"


def test_tool_use_events_print_live_activity(mocker, capsys):
    """Streamed tool_use events show up on the console as they happen, so the
    user can watch what the agent is doing while talking to it."""
    _patch_cli(mocker)
    _patch_popen(mocker, _FakeProc(_stream_lines(tool_uses=[
        ("Edit", {"file_path": "C:\\proj\\app.py"}),
        ("Bash", {"command": "pytest -q"}),
    ])))

    session = _make_session()
    session.send("fix the bug")

    out = capsys.readouterr().out
    assert "[Claude] > Edit: C:\\proj\\app.py" in out
    assert "[Claude] > Bash: pytest -q" in out


def test_missing_cli_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which", return_value=None)
    mock_popen = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.Popen")

    session = _make_session()
    result = session.send("hello")

    mock_popen.assert_not_called()
    assert result == "Claude Code isn't installed on this unit."


def test_timeout_kills_process_and_returns_spoken_safe_string(mocker):
    """When the watchdog fires, the CLI process is killed and send() returns
    the timeout message instead of a failure string."""

    class _FireNowTimer:
        def __init__(self, interval, function, args=None, kwargs=None):
            assert interval == 600  # default task_timeout_seconds reaches the watchdog
            self._function = function

        def start(self):
            self._function()

        def cancel(self):
            pass

    _patch_cli(mocker)
    mocker.patch("src.integrations.coding_agents.claude_code.threading.Timer", _FireNowTimer)
    proc = _FakeProc(lines=[], returncode=-9)
    _patch_popen(mocker, proc)

    session = _make_session()
    assert session.send("hello") == "That task timed out."
    assert proc.killed


def test_cancel_kills_in_flight_process_and_send_returns_empty(mocker):
    """cancel() from another thread kills the running CLI process; the pending
    send() returns '' so the caller knows to discard it silently."""
    _patch_cli(mocker)

    killed = threading.Event()

    class _BlockingProc:
        def __init__(self):
            self.returncode = -9
            self.stdout = self._gen()

        def _gen(self):
            killed.wait(timeout=5)
            return
            yield  # pragma: no cover — makes _gen a generator

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            killed.set()

    _patch_popen(mocker, _BlockingProc())

    session = _make_session()
    results = []
    t = threading.Thread(target=lambda: results.append(session.send("long task")))
    t.start()
    deadline = time.time() + 5
    while session._proc is None and time.time() < deadline:
        time.sleep(0.01)
    assert session._proc is not None, "send() never started the process"

    session.cancel()
    t.join(timeout=5)
    assert not t.is_alive()
    assert results == [""]
    assert killed.is_set()


def test_send_after_cancel_is_rejected_until_restart(mocker):
    _patch_cli(mocker)
    _patch_popen(mocker, _FakeProc(_stream_lines()))

    session = _make_session()
    session.cancel()
    assert session.send("hello") == ""

    session.start("C:\\proj")  # restart clears the cancelled state
    assert session.send("hello") == "Done."


def test_nonzero_exit_returns_spoken_safe_string(mocker):
    _patch_cli(mocker)
    _patch_popen(mocker, _FakeProc(lines=["some stderr noise\n"], returncode=1))

    session = _make_session()
    result = session.send("hello")

    assert "failed" in result.lower()
    # never raises, and doesn't leak a wall of stderr to TTS
    assert len(result) < 200


def test_no_result_event_returns_spoken_safe_string(mocker):
    _patch_cli(mocker)
    _patch_popen(mocker, _FakeProc(lines=["not json at all\n"], returncode=0))

    session = _make_session()
    result = session.send("hello")

    assert result == "Claude finished but returned no text."


def test_stop_clears_session_so_next_send_starts_fresh(mocker):
    _patch_cli(mocker)
    mock_popen = _patch_popen(mocker, None)
    mock_popen.side_effect = lambda *a, **k: _FakeProc(_stream_lines(session_id="sess-abc"))

    session = _make_session()
    session.send("first")
    session.stop()
    session.start("C:\\proj")
    session.send("fresh start")

    assert "--resume" not in mock_popen.call_args_list[1].args[0]
