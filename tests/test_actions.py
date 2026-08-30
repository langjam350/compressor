def _ctx(mocker, **overrides):
    from src.actions.context import ActionContext
    defaults = dict(
        unit_name="host",
        tuya=mocker.MagicMock(),
        spotify=mocker.MagicMock(),
        youtube=None,
        launcher=mocker.MagicMock(),
        network=mocker.MagicMock(),
        config={},
        host_unit_name="host",
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


def _good_match(**overrides):
    match = {"uri": "spotify:track:1", "kind": "track", "name": "Jazz", "artist": "A", "score": 0.95}
    match.update(overrides)
    return match


def test_registry_stays_in_sync_with_tool_schemas():
    """Every schema Claude can call has exactly one executable action."""
    from src.tools import TOOLS
    from src.actions import ACTIONS
    assert set(ACTIONS.keys()) == {t["name"] for t in TOOLS}
    assert all(callable(fn) for fn in ACTIONS.values())


def test_tuya_action_drives_controller(mocker):
    ctx = _ctx(mocker)
    ctx.tuya.control.return_value = "Lamp turned on."

    from src.actions import control_tuya_device
    result = control_tuya_device.run(ctx, {"device_name": "Lamp", "action": "on"})

    ctx.tuya.control.assert_called_once_with("Lamp", "on")
    assert result == "Lamp turned on."


def test_tuya_action_without_controller_reports_unconfigured(mocker):
    ctx = _ctx(mocker, tuya=None)
    from src.actions import control_tuya_device
    assert control_tuya_device.run(ctx, {"device_name": "Lamp", "action": "on"}) == "Integration not configured."


def test_spotify_action_broadcasts_for_house_speakers(mocker):
    ctx = _ctx(mocker)
    ctx.spotify.search_best.return_value = _good_match()
    ctx.spotify.play_item.return_value = "Playing Jazz by A on all house speakers."

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "jazz", "house_speakers": True})

    ctx.spotify.play_item.assert_called_once_with(_good_match(), house_speakers=True)
    ctx.network.broadcast.assert_called_once_with(
        {"type": "spotify", "action": "play", "query": "jazz"}
    )
    assert "Jazz" in result


def test_spotify_action_no_broadcast_without_house_speakers(mocker):
    ctx = _ctx(mocker)
    ctx.spotify.control.return_value = "Playback paused."

    from src.actions import control_spotify
    control_spotify.run(ctx, {"action": "pause"})

    ctx.network.broadcast.assert_not_called()


def test_spotify_action_without_controller_reports_unconfigured(mocker):
    ctx = _ctx(mocker, spotify=None)
    from src.actions import control_spotify
    assert control_spotify.run(ctx, {"action": "pause"}) == "Integration not configured."


def test_spotify_good_match_skips_youtube(mocker):
    ctx = _ctx(mocker, youtube=mocker.MagicMock())
    ctx.youtube.channel_for.return_value = None
    ctx.spotify.search_best.return_value = _good_match()
    ctx.spotify.play_item.return_value = "Playing Jazz by A."

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "jazz"})

    ctx.youtube.resolve.assert_not_called()
    assert result == "Playing Jazz by A."


def test_spotify_poor_match_falls_back_to_youtube(mocker):
    ctx = _ctx(mocker, youtube=mocker.MagicMock())
    ctx.youtube.channel_for.return_value = None
    ctx.spotify.search_best.return_value = _good_match(score=0.2)
    ctx.youtube.resolve.return_value = {"title": "Rare Remix", "url": "https://www.youtube.com/watch?v=x"}
    ctx.launcher.open.return_value = "Opening brave."

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "rare remix"})

    ctx.spotify.play_item.assert_not_called()
    ctx.launcher.open.assert_called_once_with("browser", argument="https://www.youtube.com/watch?v=x")
    assert "Rare Remix" in result and "YouTube" in result


def test_spotify_poor_match_plays_anyway_when_youtube_empty(mocker):
    ctx = _ctx(mocker, youtube=mocker.MagicMock())
    ctx.youtube.channel_for.return_value = None
    ctx.youtube.resolve.return_value = None
    ctx.spotify.search_best.return_value = _good_match(score=0.2)
    ctx.spotify.play_item.return_value = "Playing Jazz by A."

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "rare remix"})

    assert result == "Playing Jazz by A."


def test_channel_default_word_forces_youtube_over_spotify(mocker):
    ctx = _ctx(mocker, youtube=mocker.MagicMock())
    ctx.youtube.channel_for.return_value = "@LofiGirl"
    ctx.youtube.resolve.return_value = {"title": "Lofi Stream", "url": "https://www.youtube.com/watch?v=lo"}
    ctx.launcher.open.return_value = "Opening brave."

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "some lofi"})

    ctx.spotify.search_best.assert_not_called()
    ctx.launcher.open.assert_called_once_with("browser", argument="https://www.youtube.com/watch?v=lo")
    assert "Lofi Stream" in result


def test_youtube_source_from_follower_broadcasts_open_url(mocker):
    ctx = _ctx(mocker, unit_name="Kitchen", youtube=mocker.MagicMock())
    ctx.youtube.resolve.return_value = {"title": "A Video", "url": "https://www.youtube.com/watch?v=v"}

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "a video", "source": "youtube"})

    ctx.launcher.open.assert_not_called()
    ctx.network.broadcast.assert_called_once_with({
        "type": "open_url", "target_unit": "Kitchen", "url": "https://www.youtube.com/watch?v=v",
    })
    assert "Kitchen" in result


def test_youtube_house_speakers_opens_everywhere(mocker):
    ctx = _ctx(mocker, youtube=mocker.MagicMock())
    ctx.youtube.channel_for.return_value = "@LofiGirl"
    ctx.youtube.resolve.return_value = {"title": "Lofi Stream", "url": "https://www.youtube.com/watch?v=lo"}

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "lofi", "house_speakers": True})

    ctx.launcher.open.assert_called_once_with("browser", argument="https://www.youtube.com/watch?v=lo")
    ctx.network.broadcast.assert_called_once_with({
        "type": "open_url", "target_unit": None, "url": "https://www.youtube.com/watch?v=lo",
    })
    assert "everywhere" in result


def test_start_app_runs_locally_and_broadcasts_to_all_units(mocker):
    mock_app = mocker.patch("src.actions.control_spotify.spotify_app")
    ctx = _ctx(mocker, spotify=None)  # works without Spotify API credentials

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "start_app"})

    mock_app.start.assert_called_once()
    ctx.network.broadcast.assert_called_once_with({"type": "spotify_app", "action": "start"})
    assert "every unit" in result


def test_stop_app_runs_locally_and_broadcasts_to_all_units(mocker):
    mock_app = mocker.patch("src.actions.control_spotify.spotify_app")
    ctx = _ctx(mocker, spotify=None)

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "stop_app"})

    mock_app.stop.assert_called_once()
    ctx.network.broadcast.assert_called_once_with({"type": "spotify_app", "action": "stop"})
    assert "every unit" in result


def test_open_program_local_when_requester_is_host(mocker):
    ctx = _ctx(mocker, unit_name="host", host_unit_name="host")
    ctx.launcher.open.return_value = "Opening youtube in brave."

    from src.actions import open_program
    result = open_program.run(ctx, {"program": "brave", "process": "youtube", "argument": "https://youtube.com"})

    ctx.launcher.open.assert_called_once_with("brave", process="youtube", argument="https://youtube.com")
    ctx.network.broadcast.assert_not_called()
    assert result == "Opening youtube in brave."


def test_open_program_broadcasts_to_requesting_follower(mocker):
    ctx = _ctx(mocker, unit_name="Kitchen", host_unit_name="host")

    from src.actions import open_program
    result = open_program.run(ctx, {"program": "brave", "process": "youtube", "argument": "https://youtube.com"})

    ctx.launcher.open.assert_not_called()
    ctx.network.broadcast.assert_called_once_with({
        "type": "open_program",
        "target_unit": "Kitchen",
        "program": "brave",
        "process": "youtube",
        "argument": "https://youtube.com",
    })
    assert "Kitchen" in result


def test_open_program_without_launcher_reports_unconfigured(mocker):
    ctx = _ctx(mocker, launcher=None)
    from src.actions import open_program
    result = open_program.run(ctx, {"program": "brave"})
    assert "isn't configured" in result
