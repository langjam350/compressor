import pytest


def make_controller(mocker):
    mocker.patch("src.integrations.spotify.SpotifyOAuth")
    mock_sp_cls = mocker.patch("src.integrations.spotify.spotipy.Spotify")
    mock_sp = mock_sp_cls.return_value
    from src.integrations.spotify import SpotifyController
    ctrl = SpotifyController("cid", "csecret", "http://localhost:8888/callback")
    return ctrl, mock_sp


def test_pause(mocker):
    ctrl, mock_sp = make_controller(mocker)
    result = ctrl.control("pause")
    mock_sp.pause_playback.assert_called_once()
    assert "paused" in result.lower()


def test_next_track(mocker):
    ctrl, mock_sp = make_controller(mocker)
    result = ctrl.control("next")
    mock_sp.next_track.assert_called_once()
    assert "next" in result.lower()


def test_play_searches_and_starts(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {"devices": [{"id": "dev1", "is_active": True}]}
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:123", "name": "Kind of Blue", "artists": [{"name": "Miles Davis"}]}]}
    }
    result = ctrl.control("play", query="miles davis kind of blue")
    mock_sp.start_playback.assert_called_once()
    assert "Kind of Blue" in result


def test_play_on_house_speakers_starts_on_all_devices(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {
        "devices": [
            {"id": "dev1", "is_active": True},
            {"id": "dev2", "is_active": False},
        ]
    }
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:abc", "name": "Song", "artists": [{"name": "Artist"}]}]}
    }
    ctrl.control("play", query="jazz", house_speakers=True)
    assert mock_sp.start_playback.call_count == 2


def test_no_devices_returns_message(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {"devices": []}
    result = ctrl.control("play", query="jazz")
    assert "no" in result.lower() and "device" in result.lower()
