def _ctx(mocker, **overrides):
    from src.actions.context import ActionContext
    defaults = dict(
        unit_name="host",
        tuya=mocker.MagicMock(),
        spotify=mocker.MagicMock(),
        launcher=mocker.MagicMock(),
        network=mocker.MagicMock(),
        config={},
        host_unit_name="host",
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


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
    ctx.spotify.control.return_value = "Playing jazz on all house speakers."

    from src.actions import control_spotify
    result = control_spotify.run(ctx, {"action": "play", "query": "jazz", "house_speakers": True})

    ctx.spotify.control.assert_called_once_with("play", "jazz", house_speakers=True)
    ctx.network.broadcast.assert_called_once_with(
        {"type": "spotify", "action": "play", "query": "jazz"}
    )
    assert "jazz" in result


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
