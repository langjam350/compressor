"""Assistant-level ownership: electing a role at startup, and the handover
when the home unit drops out or comes back."""

import json

import pytest


UNITS = {
    "units": [
        {"name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100", "host_port": 8765},
        {"name": "Personal Laptop", "priority": 2, "host_ip": "192.168.0.166", "host_port": 8765},
    ]
}


@pytest.fixture
def units_path(tmp_path):
    p = tmp_path / "units.json"
    p.write_text(json.dumps(UNITS))
    return str(p)


def build(mocker, units_path, unit_name, reachable, *, api_key="key123"):
    """An Assistant with every side effect stubbed, whose peer probes succeed
    only for the units named in `reachable` (a mutable set the test can edit
    between election rounds)."""
    config = {
        "wake_word": "compressor",
        "host_port": 8765,
        "tuya": {"devices": [{"name": "Living Room Light"}]},
    }
    if api_key:
        config["anthropic_api_key"] = api_key

    mocker.patch("src.assistant.load_config", return_value=config)
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.AIClient")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.SpotifyController")
    mocker.patch("src.assistant.action_log.configure")
    mocker.patch("src.cluster.probe", side_effect=lambda unit, timeout: unit.name in reachable)

    network = mocker.MagicMock()
    network.get_info.return_value = {"city": "Chicago"}
    mocker.patch("src.assistant.NetworkClient", return_value=network)
    scheduler = mocker.MagicMock()
    mocker.patch("src.assistant.Scheduler", return_value=scheduler)

    from src.assistant import Assistant

    assistant = Assistant(unit_name=unit_name, units_path=units_path)
    return assistant, network, scheduler


def test_home_unit_owns_the_system_at_startup(mocker, units_path):
    assistant, network, scheduler = build(mocker, units_path, "Personal Desktop", set())

    assert assistant._role == "host"
    assert assistant._tuya is not None
    scheduler.start.assert_called_once()
    network.set_host.assert_any_call("127.0.0.1", 8765)


def test_second_unit_follows_the_home_unit_when_it_is_up(mocker, units_path):
    assistant, network, scheduler = build(
        mocker, units_path, "Personal Laptop", {"Personal Desktop"}
    )

    assert assistant._role == "follower"
    assert assistant._tuya is None
    assert assistant._spotify is None
    scheduler.start.assert_not_called()
    network.set_host.assert_called_once_with("192.168.0.100", 8765)


def test_second_unit_takes_over_when_the_home_unit_is_down(mocker, units_path):
    assistant, network, scheduler = build(mocker, units_path, "Personal Laptop", set())

    assert assistant._role == "host"
    assert assistant._tuya is not None
    scheduler.start.assert_called_once()


def test_unit_without_an_api_key_never_takes_over(mocker, units_path):
    assistant, network, scheduler = build(
        mocker, units_path, "Personal Laptop", set(), api_key=None
    )

    assert assistant._role == "follower"
    scheduler.start.assert_not_called()


def test_health_advertises_ownership(mocker, units_path):
    from src.network.host_server import app

    build(mocker, units_path, "Personal Laptop", set())

    assert app.state.unit_name == "Personal Laptop"
    assert app.state.owner is True
    assert app.state.priority == 2


def test_follower_does_not_advertise_ownership_or_serve_queries(mocker, units_path):
    from src.network.host_server import app

    build(mocker, units_path, "Personal Laptop", {"Personal Desktop"})

    assert app.state.owner is False
    assert app.state.query_handler is None


def test_handing_ownership_back_tears_down_host_state(mocker, units_path):
    from src.network.host_server import app

    reachable = set()
    assistant, network, scheduler = build(mocker, units_path, "Personal Laptop", reachable)
    assert assistant._role == "host"

    reachable.add("Personal Desktop")  # home unit comes back
    assistant._coordinator.run_round(assistant._on_owner_change)

    assert assistant._role == "follower"
    assert assistant._tuya is None
    assert assistant._spotify is None
    assert assistant._system_prompt is None
    assert app.state.owner is False
    assert app.state.query_handler is None
    scheduler.stop.assert_called_once()
    network.set_host.assert_called_with("192.168.0.100", 8765)


def test_taking_over_builds_host_state_and_announces(mocker, units_path):
    from src.network.host_server import app

    reachable = {"Personal Desktop"}
    assistant, network, scheduler = build(mocker, units_path, "Personal Laptop", reachable)
    assert assistant._role == "follower"

    reachable.clear()  # home unit drops out
    for _ in range(3):  # promotion needs consecutive misses
        assistant._coordinator.run_round(assistant._on_owner_change)

    assert assistant._role == "host"
    assert assistant._tuya is not None
    assert app.state.owner is True
    assert app.state.query_handler == assistant._process_query
    assistant._tts.speak.assert_any_call("Taking over as the main unit.")


def test_pinned_role_in_config_skips_the_election(mocker, units_path):
    mocker.patch("src.assistant.load_config", return_value={
        "role": "host",
        "wake_word": "compressor",
        "anthropic_api_key": "key123",
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.AIClient")
    mocker.patch("src.assistant.TuyaController")
    mocker.patch("src.assistant.Scheduler")
    mocker.patch("src.assistant.action_log.configure")
    load = mocker.patch("src.assistant.UnitRegistry.load")

    from src.assistant import Assistant

    assistant = Assistant(unit_name="Personal Laptop", units_path=units_path)

    assert assistant._role == "host"
    assert assistant._coordinator is None
    load.assert_not_called()


def test_missing_units_file_without_a_pinned_role_is_a_clear_error(mocker, tmp_path):
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "anthropic_api_key": "key123",
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.action_log.configure")

    from src.assistant import Assistant
    from src.cluster import ClusterError

    with pytest.raises(ClusterError, match="no 'role:' pinned"):
        Assistant(unit_name="Personal Laptop", units_path=str(tmp_path / "missing.json"))


def test_unknown_unit_name_names_the_registered_units(mocker, units_path):
    mocker.patch("src.assistant.load_config", return_value={
        "wake_word": "compressor",
        "anthropic_api_key": "key123",
    })
    mocker.patch("src.assistant.TTSEngine", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.SpeechListener", return_value=mocker.MagicMock())
    mocker.patch("src.assistant.NetworkClient")
    mocker.patch("src.assistant.run_server")
    mocker.patch("src.assistant.threading.Thread")
    mocker.patch("src.assistant.time.sleep")
    mocker.patch("src.assistant.action_log.configure")

    from src.assistant import Assistant
    from src.cluster import ClusterError

    with pytest.raises(ClusterError, match="Personal Desktop"):
        Assistant(unit_name="Basement Pi", units_path=units_path)
