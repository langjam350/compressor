import json
import subprocess


def _mock_run_result(mocker, result_text="Done.", session_id="sess-123", returncode=0, stderr=""):
    proc = mocker.Mock()
    proc.returncode = returncode
    proc.stdout = json.dumps({"result": result_text, "session_id": session_id})
    proc.stderr = stderr
    return proc


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


def test_factory_unknown_agent_returns_stub_with_spoken_message():
    from src.integrations.coding_agents import create_session
    session = create_session({"agent": "gemini_cli"})
    session.start("C:\\proj")
    result = session.send("do something")
    assert result == "Coding agent 'gemini_cli' isn't supported on this unit."
    session.stop()  # must not raise


def test_send_builds_expected_first_command(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker))

    session = _make_session()
    result = session.send("add a button")

    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "C:\\npm\\claude.cmd"
    assert cmd[1:3] == ["-p", "add a button"]
    assert "--resume" not in cmd
    assert "--model" not in cmd  # unset -> omitted
    assert ["--output-format", "json"] == cmd[cmd.index("--output-format"):cmd.index("--output-format") + 2]
    assert ["--permission-mode", "acceptEdits"] == cmd[cmd.index("--permission-mode"):cmd.index("--permission-mode") + 2]
    assert ["--add-dir", "C:\\proj"] == cmd[cmd.index("--add-dir"):cmd.index("--add-dir") + 2]
    assert ["--max-turns", "25"] == cmd[cmd.index("--max-turns"):cmd.index("--max-turns") + 2]
    assert "--append-system-prompt" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert mock_run.call_args.kwargs["cwd"] == "C:\\proj"
    assert mock_run.call_args.kwargs["timeout"] == 600
    assert result == "Done."


def test_second_send_resumes_captured_session_id(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker, session_id="sess-abc"))

    session = _make_session()
    session.send("first")
    session.send("second")

    second_cmd = mock_run.call_args_list[1].args[0]
    idx = second_cmd.index("--resume")
    assert second_cmd[idx + 1] == "sess-abc"


def test_model_flag_present_only_when_configured(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker))

    session = _make_session(model="claude-sonnet-5")
    session.send("hello")

    cmd = mock_run.call_args.args[0]
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "claude-sonnet-5"


def test_missing_cli_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which", return_value=None)
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run")

    session = _make_session()
    result = session.send("hello")

    mock_run.assert_not_called()
    assert result == "Claude Code isn't installed on this unit."


def test_timeout_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                 side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=600))

    session = _make_session()
    assert session.send("hello") == "That task timed out."


def test_nonzero_exit_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                 return_value=_mock_run_result(mocker, returncode=1, stderr="boom"))

    session = _make_session()
    result = session.send("hello")

    assert "failed" in result.lower()
    # never raises, and doesn't leak a wall of stderr to TTS
    assert len(result) < 200


def test_bad_json_returns_spoken_safe_string(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    proc = mocker.Mock()
    proc.returncode = 0
    proc.stdout = "not json at all"
    proc.stderr = ""
    mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run", return_value=proc)

    session = _make_session()
    result = session.send("hello")

    assert "failed" in result.lower()


def test_stop_clears_session_so_next_send_starts_fresh(mocker):
    mocker.patch("src.integrations.coding_agents.claude_code.shutil.which",
                 return_value="C:\\npm\\claude.cmd")
    mock_run = mocker.patch("src.integrations.coding_agents.claude_code.subprocess.run",
                            return_value=_mock_run_result(mocker, session_id="sess-abc"))

    session = _make_session()
    session.send("first")
    session.stop()
    session.start("C:\\proj")
    session.send("fresh start")

    assert "--resume" not in mock_run.call_args_list[1].args[0]
