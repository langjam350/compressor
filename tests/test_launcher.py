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
