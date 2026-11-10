from datetime import datetime


def _ctx(mocker, **overrides):
    from src.actions.context import ActionContext
    defaults = dict(
        unit_name="host",
        host_unit_name="host",
        network=mocker.MagicMock(),
        known_units=["host", "Kitchen"],
        schedule_wezterm_send=mocker.Mock(),
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


def test_schedules_locally_when_target_is_the_host(mocker):
    ctx = _ctx(mocker)
    from src.actions import message_wezterm_tab
    result = message_wezterm_tab.run(ctx, {"tab_name": "jldesigns", "message": "continue", "hour": 15})

    ctx.schedule_wezterm_send.assert_called_once()
    ctx.network.broadcast.assert_not_called()
    payload = ctx.schedule_wezterm_send.call_args[0][0]
    assert payload["target_unit"] == "host"
    assert payload["tab_name"] == "jldesigns"
    assert payload["message"] == "continue"
    assert "jldesigns" in result


def test_broadcasts_when_target_is_a_different_unit(mocker):
    ctx = _ctx(mocker)
    from src.actions import message_wezterm_tab
    message_wezterm_tab.run(ctx, {
        "tab_name": "jldesigns", "message": "continue", "hour": 15, "unit": "Kitchen",
    })

    ctx.schedule_wezterm_send.assert_not_called()
    ctx.network.broadcast.assert_called_once()
    payload = ctx.network.broadcast.call_args[0][0]
    assert payload["target_unit"] == "Kitchen"


def test_defaults_target_unit_to_the_requesting_unit(mocker):
    ctx = _ctx(mocker, unit_name="Kitchen")
    from src.actions import message_wezterm_tab
    message_wezterm_tab.run(ctx, {"tab_name": "jldesigns", "message": "continue", "hour": 15})

    payload = ctx.network.broadcast.call_args[0][0]
    assert payload["target_unit"] == "Kitchen"


def test_rejects_unknown_unit(mocker):
    ctx = _ctx(mocker)
    from src.actions import message_wezterm_tab
    result = message_wezterm_tab.run(ctx, {
        "tab_name": "jldesigns", "message": "continue", "hour": 15, "unit": "Garage",
    })

    assert result == "No unit named 'Garage' in your setup."
    ctx.schedule_wezterm_send.assert_not_called()
    ctx.network.broadcast.assert_not_called()


def test_time_already_passed_today_schedules_for_tomorrow(mocker):
    ctx = _ctx(mocker)
    fixed_fire_at = datetime(2026, 1, 2, 15, 0)
    mocker.patch("src.actions.message_wezterm_tab._compute_fire_at", return_value=(fixed_fire_at, True))

    from src.actions import message_wezterm_tab
    result = message_wezterm_tab.run(ctx, {"tab_name": "jldesigns", "message": "continue", "hour": 15})

    payload = ctx.schedule_wezterm_send.call_args[0][0]
    assert payload["fire_at"] == fixed_fire_at.isoformat()
    assert "tomorrow" in result


def test_compute_fire_at_stays_today_when_time_is_still_ahead():
    from src.actions.message_wezterm_tab import _compute_fire_at
    now = datetime(2026, 1, 1, 10, 0)
    fire_at, tomorrow = _compute_fire_at(15, 0, now=now)
    assert fire_at == datetime(2026, 1, 1, 15, 0)
    assert tomorrow is False


def test_compute_fire_at_rolls_to_tomorrow_when_time_already_passed():
    from src.actions.message_wezterm_tab import _compute_fire_at
    now = datetime(2026, 1, 1, 16, 0)
    fire_at, tomorrow = _compute_fire_at(15, 0, now=now)
    assert fire_at == datetime(2026, 1, 2, 15, 0)
    assert tomorrow is True


def test_compute_fire_at_treats_exact_current_time_as_passed():
    from src.actions.message_wezterm_tab import _compute_fire_at
    now = datetime(2026, 1, 1, 15, 0)
    fire_at, tomorrow = _compute_fire_at(15, 0, now=now)
    assert fire_at == datetime(2026, 1, 2, 15, 0)
    assert tomorrow is True
