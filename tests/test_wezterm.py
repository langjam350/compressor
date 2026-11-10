def test_find_pane_by_tab_title_matches_case_insensitively(mocker):
    mocker.patch("src.integrations.wezterm.shutil.which", return_value="/usr/bin/wezterm")
    mocker.patch("src.integrations.wezterm.subprocess.run", return_value=mocker.Mock(
        returncode=0,
        stdout='[{"pane_id": 1, "tab_title": "JLDesigns", "is_active": true}]',
    ))

    from src.integrations import wezterm
    assert wezterm.find_pane_by_tab_title("jldesigns") == 1


def test_find_pane_by_tab_title_falls_back_to_pane_title(mocker):
    mocker.patch("src.integrations.wezterm.shutil.which", return_value="/usr/bin/wezterm")
    mocker.patch("src.integrations.wezterm.subprocess.run", return_value=mocker.Mock(
        returncode=0,
        stdout='[{"pane_id": 7, "title": "jldesigns", "is_active": true}]',
    ))

    from src.integrations import wezterm
    assert wezterm.find_pane_by_tab_title("jldesigns") == 7


def test_find_pane_by_tab_title_returns_none_when_no_match(mocker):
    mocker.patch("src.integrations.wezterm.shutil.which", return_value="/usr/bin/wezterm")
    mocker.patch("src.integrations.wezterm.subprocess.run", return_value=mocker.Mock(
        returncode=0, stdout="[]",
    ))

    from src.integrations import wezterm
    assert wezterm.find_pane_by_tab_title("nope") is None


def test_find_pane_by_tab_title_prefers_active_pane_among_duplicates(mocker):
    mocker.patch("src.integrations.wezterm.shutil.which", return_value="/usr/bin/wezterm")
    mocker.patch("src.integrations.wezterm.subprocess.run", return_value=mocker.Mock(
        returncode=0,
        stdout='[{"pane_id": 1, "tab_title": "work", "is_active": false}, '
               '{"pane_id": 2, "tab_title": "work", "is_active": true}]',
    ))

    from src.integrations import wezterm
    assert wezterm.find_pane_by_tab_title("work") == 2


def test_send_to_tab_reports_missing_wezterm_cli(mocker):
    mocker.patch("src.integrations.wezterm.shutil.which", return_value=None)

    from src.integrations import wezterm
    result = wezterm.send_to_tab("jldesigns", "continue")
    assert "Couldn't reach WezTerm" in result


def test_send_to_tab_reports_missing_tab(mocker):
    mocker.patch("src.integrations.wezterm.find_pane_by_tab_title", return_value=None)

    from src.integrations import wezterm
    result = wezterm.send_to_tab("jldesigns", "continue")
    assert "No WezTerm tab named 'jldesigns' found." == result


def test_send_to_tab_sends_text_with_enter(mocker):
    mocker.patch("src.integrations.wezterm.find_pane_by_tab_title", return_value=3)
    mocker.patch("src.integrations.wezterm.shutil.which", return_value="/usr/bin/wezterm")
    mock_run = mocker.patch("src.integrations.wezterm.subprocess.run")

    from src.integrations import wezterm
    result = wezterm.send_to_tab("jldesigns", "continue please")

    args = mock_run.call_args[0][0]
    assert args[:3] == ["/usr/bin/wezterm", "cli", "send-text"]
    assert "3" in args
    assert args[-1] == "continue please\r"
    assert "Sent message to 'jldesigns'." == result
