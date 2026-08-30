import pytest


def make_controller(mocker, app_starter=None):
    mocker.patch("src.integrations.spotify.SpotifyOAuth")
    mock_sp_cls = mocker.patch("src.integrations.spotify.spotipy.Spotify")
    mock_sp = mock_sp_cls.return_value
    from src.integrations.spotify import SpotifyController
    ctrl = SpotifyController("cid", "csecret", "http://localhost:8888/callback", app_starter=app_starter)
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
    mock_sp.start_playback.assert_called_once_with(device_id="dev1", uris=["spotify:track:123"])
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
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:1", "name": "Jazz", "artists": [{"name": "A"}]}]}
    }
    result = ctrl.control("play", query="jazz")
    assert "no" in result.lower() and "device" in result.lower()


# --------------------------------------------------------------------- #
# Alexa-style lookup (search_best / play_item)                          #
# --------------------------------------------------------------------- #

def test_search_best_scopes_to_named_kind(mocker):
    """query_type 'album' searches only albums and plays a context URI."""
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {"devices": [{"id": "dev1", "is_active": True}]}
    mock_sp.search.return_value = {
        "albums": {"items": [{"uri": "spotify:album:1", "name": "Kind of Blue", "artists": [{"name": "Miles Davis"}]}]}
    }
    result = ctrl.control("play", query="kind of blue", query_type="album")
    assert mock_sp.search.call_args.kwargs["type"] == "album"
    mock_sp.start_playback.assert_called_once_with(device_id="dev1", context_uri="spotify:album:1")
    assert "album" in result.lower() and "Kind of Blue" in result


def test_search_best_auto_prefers_closest_name_match(mocker):
    """'play radiohead' should match the artist over a poorly-named track."""
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:1", "name": "Radiohead Tribute Medley", "artists": [{"name": "Cover Band"}], "popularity": 10}]},
        "artists": {"items": [{"uri": "spotify:artist:1", "name": "Radiohead", "popularity": 85}]},
        "albums": {"items": []},
    }
    best = ctrl.search_best("radiohead", "auto")
    assert best["kind"] == "artist"
    assert best["name"] == "Radiohead"
    assert best["score"] >= 0.9


def test_search_best_returns_none_when_empty(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.search.return_value = {"tracks": {"items": []}, "artists": {"items": []}, "albums": {"items": []}}
    assert ctrl.search_best("xyzzy", "auto") is None


def test_play_artist_uses_context_uri(mocker):
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.devices.return_value = {"devices": [{"id": "dev1", "is_active": True}]}
    result = ctrl.play_item({"uri": "spotify:artist:1", "kind": "artist", "name": "Radiohead", "artist": "", "score": 1.0})
    mock_sp.start_playback.assert_called_once_with(device_id="dev1", context_uri="spotify:artist:1")
    assert "Radiohead" in result


def test_low_score_match_is_flagged_below_threshold(mocker):
    """A bad name match must score under GOOD_MATCH_THRESHOLD so the
    action layer knows to try YouTube."""
    from src.integrations.spotify import GOOD_MATCH_THRESHOLD
    ctrl, mock_sp = make_controller(mocker)
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:1", "name": "Completely Unrelated", "artists": [{"name": "Someone"}], "popularity": 5}]},
        "artists": {"items": []},
        "albums": {"items": []},
    }
    best = ctrl.search_best("obscure youtube-only remix", "auto")
    assert best is not None
    assert best["score"] < GOOD_MATCH_THRESHOLD


# --------------------------------------------------------------------- #
# App auto-start when no Connect device exists                           #
# --------------------------------------------------------------------- #

def test_play_with_no_devices_starts_app_and_retries(mocker):
    starter = mocker.MagicMock()
    ctrl, mock_sp = make_controller(mocker, app_starter=starter)
    mocker.patch("src.integrations.spotify.time.sleep")
    mock_sp.devices.side_effect = [
        {"devices": []},                                    # initial check
        {"devices": [{"id": "dev1", "is_active": True}]},   # after app start
    ]
    mock_sp.search.return_value = {
        "tracks": {"items": [{"uri": "spotify:track:1", "name": "Jazz", "artists": [{"name": "A"}]}]}
    }
    result = ctrl.control("play", query="jazz")
    starter.assert_called_once()
    mock_sp.start_playback.assert_called_once_with(device_id="dev1", uris=["spotify:track:1"])
    assert "Jazz" in result


def test_resume_with_no_devices_starts_app_and_retries(mocker):
    starter = mocker.MagicMock()
    ctrl, mock_sp = make_controller(mocker, app_starter=starter)
    mocker.patch("src.integrations.spotify.time.sleep")
    mock_sp.devices.side_effect = [
        {"devices": []},
        {"devices": [{"id": "dev1", "is_active": True}]},
    ]
    result = ctrl.control("play")
    starter.assert_called_once()
    assert "resuming" in result.lower()


def test_app_starter_failure_degrades_to_no_device_message(mocker):
    starter = mocker.MagicMock(side_effect=RuntimeError("boom"))
    ctrl, mock_sp = make_controller(mocker, app_starter=starter)
    mock_sp.devices.return_value = {"devices": []}
    result = ctrl.control("play")
    assert "no" in result.lower() and "device" in result.lower()
