from src.integrations import spotify_app


def _proc(mocker, name):
    proc = mocker.MagicMock()
    proc.info = {"name": name}
    return proc


def test_start_launches_via_protocol_when_not_running(mocker):
    mocker.patch("src.integrations.spotify_app.psutil.process_iter", return_value=[])
    startfile = mocker.patch("src.integrations.spotify_app.os.startfile")
    result = spotify_app.start()
    startfile.assert_called_once_with("spotify:")
    assert "starting" in result.lower()


def test_start_skips_when_already_running(mocker):
    mocker.patch(
        "src.integrations.spotify_app.psutil.process_iter",
        return_value=[_proc(mocker, "Spotify.exe")],
    )
    startfile = mocker.patch("src.integrations.spotify_app.os.startfile")
    result = spotify_app.start()
    startfile.assert_not_called()
    assert "already running" in result.lower()


def test_start_failure_returns_message_not_exception(mocker):
    mocker.patch("src.integrations.spotify_app.psutil.process_iter", return_value=[])
    mocker.patch(
        "src.integrations.spotify_app.os.startfile",
        side_effect=OSError("no protocol handler"),
    )
    result = spotify_app.start()
    assert "couldn't" in result.lower()


def test_stop_terminates_all_spotify_processes(mocker):
    spotify_proc = _proc(mocker, "Spotify.exe")
    other_proc = _proc(mocker, "notepad.exe")
    mocker.patch(
        "src.integrations.spotify_app.psutil.process_iter",
        return_value=[spotify_proc, other_proc],
    )
    result = spotify_app.stop()
    spotify_proc.terminate.assert_called_once()
    other_proc.terminate.assert_not_called()
    assert "closed" in result.lower()


def test_stop_when_not_running_reports_it(mocker):
    mocker.patch("src.integrations.spotify_app.psutil.process_iter", return_value=[])
    result = spotify_app.stop()
    assert "isn't running" in result.lower()
