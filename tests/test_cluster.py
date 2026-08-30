import json

import pytest

from src.cluster import ClusterError, Coordinator, Unit, UnitRegistry, probe

DESKTOP = Unit("Personal Desktop", 1, "192.168.0.100", 8765)
LAPTOP = Unit("Personal Laptop", 2, "192.168.0.166", 8765)
TABLET = Unit("Kitchen Tablet", 3, "192.168.0.200", 8765)


def write_units(tmp_path, payload) -> str:
    p = tmp_path / "units.json"
    p.write_text(json.dumps(payload))
    return str(p)


# ---------------------------------------------------------------- registry


def test_load_orders_units_by_priority(tmp_path):
    path = write_units(tmp_path, {"units": [
        {"name": "Personal Laptop", "priority": 2, "host_ip": "192.168.0.166"},
        {"name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100"},
    ]})
    registry = UnitRegistry.load(path)
    assert [u.name for u in registry.units] == ["Personal Desktop", "Personal Laptop"]


def test_load_defaults_the_port(tmp_path):
    path = write_units(tmp_path, {"units": [
        {"name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100"},
    ]})
    assert UnitRegistry.load(path).units[0].host_port == 8765


def test_load_ignores_unknown_keys(tmp_path):
    path = write_units(tmp_path, {"units": [
        {"name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100",
         "note": "human-readable comment, not schema"},
    ]})
    assert UnitRegistry.load(path).units[0].name == "Personal Desktop"


def test_load_rejects_missing_fields(tmp_path):
    path = write_units(tmp_path, {"units": [{"name": "Personal Desktop", "priority": 1}]})
    with pytest.raises(ClusterError, match="host_ip"):
        UnitRegistry.load(path)


def test_load_rejects_duplicate_priorities(tmp_path):
    path = write_units(tmp_path, {"units": [
        {"name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100"},
        {"name": "Personal Laptop", "priority": 1, "host_ip": "192.168.0.166"},
    ]})
    with pytest.raises(ClusterError, match="share priority"):
        UnitRegistry.load(path)


def test_load_rejects_duplicate_names(tmp_path):
    path = write_units(tmp_path, {"units": [
        {"name": "Personal Desktop", "priority": 1, "host_ip": "192.168.0.100"},
        {"name": "personal desktop", "priority": 2, "host_ip": "192.168.0.166"},
    ]})
    with pytest.raises(ClusterError, match="Duplicate unit name"):
        UnitRegistry.load(path)


def test_load_rejects_malformed_json(tmp_path):
    p = tmp_path / "units.json"
    p.write_text("{not json")
    with pytest.raises(ClusterError, match="not valid JSON"):
        UnitRegistry.load(str(p))


def test_load_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        UnitRegistry.load(str(tmp_path / "nope.json"))


def test_get_is_case_insensitive():
    registry = UnitRegistry([DESKTOP, LAPTOP])
    assert registry.get("personal LAPTOP") == LAPTOP


def test_get_unknown_name_lists_known_units():
    registry = UnitRegistry([DESKTOP, LAPTOP])
    with pytest.raises(ClusterError) as exc:
        registry.get("Personal Phone")
    assert "Personal Desktop" in str(exc.value)
    assert "Personal Laptop" in str(exc.value)


def test_ahead_of_returns_only_higher_priority_units():
    registry = UnitRegistry([DESKTOP, LAPTOP, TABLET])
    assert registry.ahead_of(LAPTOP) == [DESKTOP]
    assert registry.ahead_of(DESKTOP) == []
    assert registry.ahead_of(TABLET) == [DESKTOP, LAPTOP]


# ------------------------------------------------------------------- probe


def test_probe_true_when_peer_claims_ownership(mocker):
    mocker.patch("src.cluster.httpx.get").return_value.json.return_value = {
        "unit_name": "Personal Desktop", "owner": True,
    }
    assert probe(DESKTOP) is True


def test_probe_false_when_peer_is_up_but_following(mocker):
    mocker.patch("src.cluster.httpx.get").return_value.json.return_value = {
        "unit_name": "Personal Desktop", "owner": False,
    }
    assert probe(DESKTOP) is False


def test_probe_false_when_peer_answers_under_a_different_name(mocker):
    mocker.patch("src.cluster.httpx.get").return_value.json.return_value = {
        "unit_name": "Personal Laptop", "owner": True,
    }
    assert probe(DESKTOP) is False


def test_probe_false_when_unreachable(mocker):
    mocker.patch("src.cluster.httpx.get", side_effect=Exception("no route to host"))
    assert probe(DESKTOP) is False


# -------------------------------------------------------------- coordinator


def coordinator(self_name, reachable, **kwargs):
    """A Coordinator whose probes succeed only for units named in `reachable`."""
    registry = UnitRegistry([DESKTOP, LAPTOP, TABLET])
    return Coordinator(
        registry,
        self_name,
        prober=lambda unit, timeout: unit.name in reachable,
        **kwargs,
    )


def test_top_priority_unit_owns_without_probing_anyone():
    probed = []
    registry = UnitRegistry([DESKTOP, LAPTOP])

    def spy(unit, timeout):
        probed.append(unit.name)
        return True

    coord = Coordinator(registry, "Personal Desktop", prober=spy)
    assert coord.decide() == DESKTOP
    assert probed == []


def test_second_unit_follows_the_home_unit_when_it_answers():
    assert coordinator("Personal Laptop", {"Personal Desktop"}).decide() == DESKTOP


def test_second_unit_takes_over_when_the_home_unit_is_down():
    assert coordinator("Personal Laptop", set()).decide() == LAPTOP


def test_third_unit_prefers_the_highest_priority_unit_that_answers():
    coord = coordinator("Kitchen Tablet", {"Personal Desktop", "Personal Laptop"})
    assert coord.decide() == DESKTOP


def test_third_unit_falls_to_the_stand_in_when_home_is_down():
    assert coordinator("Kitchen Tablet", {"Personal Laptop"}).decide() == LAPTOP


def test_ineligible_unit_never_promotes_itself():
    coord = coordinator("Personal Laptop", set(), eligible=False)
    assert coord.decide() is None


def test_ineligible_unit_follows_a_lower_priority_owner():
    coord = coordinator("Personal Laptop", {"Kitchen Tablet"}, eligible=False)
    assert coord.decide() == TABLET


def test_start_returns_the_initial_owner_without_calling_back():
    changes = []
    coord = coordinator("Personal Laptop", {"Personal Desktop"}, poll_seconds=3600)
    try:
        assert coord.start(changes.append) == DESKTOP
        assert changes == []  # the caller applies the initial decision itself
    finally:
        coord.stop()


def test_promotion_needs_several_consecutive_misses():
    reachable = {"Personal Desktop"}
    coord = coordinator("Personal Laptop", reachable, promote_after_misses=3)
    coord._current = DESKTOP
    changes = []

    reachable.clear()
    for _ in range(2):
        coord.run_round(changes.append)
        assert changes == []  # a dropped probe or two must not churn the host
    coord.run_round(changes.append)
    assert changes == [LAPTOP]


def test_a_recovered_probe_resets_the_miss_count():
    reachable = {"Personal Desktop"}
    coord = coordinator("Personal Laptop", reachable, promote_after_misses=2)
    coord._current = DESKTOP
    changes = []

    reachable.clear()
    coord.run_round(changes.append)      # miss 1
    reachable.add("Personal Desktop")
    coord.run_round(changes.append)      # back — streak broken
    reachable.clear()
    coord.run_round(changes.append)      # miss 1 again, not 2
    assert changes == []


def test_demotion_is_immediate_when_the_home_unit_returns():
    reachable = set()
    coord = coordinator("Personal Laptop", reachable, promote_after_misses=3)
    coord._current = LAPTOP
    changes = []

    reachable.add("Personal Desktop")
    coord.run_round(changes.append)
    assert changes == [DESKTOP]


def test_round_survives_a_failing_change_handler():
    coord = coordinator("Personal Laptop", set(), promote_after_misses=1)
    coord._current = DESKTOP

    def boom(owner):
        raise RuntimeError("handler exploded")

    assert coord.run_round(boom) == LAPTOP  # must not raise


def test_round_keeps_the_current_owner_when_deciding_raises():
    registry = UnitRegistry([DESKTOP, LAPTOP])

    def broken(unit, timeout):
        raise RuntimeError("socket layer exploded")

    coord = Coordinator(registry, "Personal Laptop", prober=broken)
    coord._current = DESKTOP
    changes = []
    assert coord.run_round(changes.append) == DESKTOP
    assert changes == []
