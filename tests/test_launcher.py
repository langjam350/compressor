import yaml

PROGRAMS = [
    {
        "name": "brave",
        "launch": "brave",
        "process_name": "brave",
        "aliases": ["browser"],
        "processes": {"youtube": "https://youtube.com"},
    },
    {"name": "notepad", "launch": "notepad", "process_name": "notepad"},
]


def _launcher(tmp_path, programs=None):
    from src.integrations.launcher import ProgramLauncher
    return ProgramLauncher(
        programs if programs is not None else PROGRAMS,
        learned_path=str(tmp_path / "programs_learned.yaml"),
        unit_name="TestUnit",
    )


def test_exact_name_match_launches(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("notepad")

    mock_start.assert_called_once_with("notepad")
    assert "Opening notepad" in result


def test_alias_match(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("browser")

    mock_start.assert_called_once_with("brave")
    assert "brave" in result.lower()


def test_substring_fallback_match(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    _launcher(tmp_path).open("brave browser")

    mock_start.assert_called_once_with("brave")


def test_unknown_program_reports_unconfigured(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    result = _launcher(tmp_path).open("photoshop")

    mock_start.assert_not_called()
    assert "isn't configured" in result
    assert "TestUnit" in result


def test_bare_launch_skipped_when_already_running(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=True)

    result = _launcher(tmp_path).open("notepad")

    mock_start.assert_not_called()
    assert "already running" in result


def test_known_process_uses_tree_value_over_argument(mocker, tmp_path):
    """Stored tree wins over Claude's best-guess argument."""
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    _launcher(tmp_path).open("brave", process="youtube", argument="https://wrong-guess.example")

    mock_start.assert_called_once_with("brave", arguments="https://youtube.com")


def test_argument_launch_skips_already_running_check(mocker, tmp_path):
    """A URL at a running browser opens as a new tab — launch anyway."""
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    running = mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=True)

    _launcher(tmp_path).open("brave", process="youtube", argument=None)

    mock_start.assert_called_once_with("brave", arguments="https://youtube.com")
    running.assert_not_called()


def test_launch_failure_returns_string_not_raise(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile", side_effect=OSError("no association"))
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("notepad")

    assert "Couldn't open" in result


def test_empty_program_string_matches_nothing(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    result = _launcher(tmp_path).open("")

    mock_start.assert_not_called()
    assert "isn't configured" in result


def test_whitespace_program_string_matches_nothing(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    result = _launcher(tmp_path).open("   ")

    mock_start.assert_not_called()
    assert "isn't configured" in result


def test_unknown_process_executes_argument_and_learns(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    learned_file = tmp_path / "programs_learned.yaml"

    launcher = _launcher(tmp_path)
    result = launcher.open("brave", process="reddit", argument="https://reddit.com")

    mock_start.assert_called_once_with("brave", arguments="https://reddit.com")
    assert "reddit" in result
    saved = yaml.safe_load(learned_file.read_text())
    assert saved == {"brave": {"reddit": "https://reddit.com"}}


def test_learned_process_used_on_next_call(mocker, tmp_path):
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")

    launcher = _launcher(tmp_path)
    launcher.open("brave", process="reddit", argument="https://reddit.com")
    mock_start.reset_mock()

    # Fresh instance simulates a restart: learned file must be re-read.
    launcher2 = _launcher(tmp_path)
    launcher2.open("brave", process="reddit", argument="https://a-different-guess.example")

    mock_start.assert_called_once_with("brave", arguments="https://reddit.com")


def test_config_processes_win_over_learned(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile")
    (tmp_path / "programs_learned.yaml").write_text(
        yaml.dump({"brave": {"youtube": "https://evil-learned.example"}})
    )

    launcher = _launcher(tmp_path)
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    launcher.open("brave", process="youtube", argument=None)

    mock_start.assert_called_once_with("brave", arguments="https://youtube.com")


def test_failed_launch_does_not_learn(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile", side_effect=OSError("boom"))
    learned_file = tmp_path / "programs_learned.yaml"

    launcher = _launcher(tmp_path)
    result = launcher.open("brave", process="reddit", argument="https://reddit.com")

    assert "Couldn't open" in result
    assert not learned_file.exists()


def test_corrupt_learned_file_treated_as_empty(mocker, tmp_path):
    (tmp_path / "programs_learned.yaml").write_text("][ not yaml: [")
    mock_start = mocker.patch("src.integrations.launcher.os.startfile")
    mocker.patch("src.integrations.launcher.ProgramLauncher._is_running", return_value=False)

    result = _launcher(tmp_path).open("notepad")

    assert "Opening notepad" in result


def test_learning_writes_action_log_event(mocker, tmp_path):
    mocker.patch("src.integrations.launcher.os.startfile")
    mock_log = mocker.patch("src.integrations.launcher.action_log.log_process_learned")

    _launcher(tmp_path).open("brave", process="reddit", argument="https://reddit.com")

    mock_log.assert_called_once_with("TestUnit", "brave", "reddit", "https://reddit.com")
