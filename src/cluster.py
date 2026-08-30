"""Cluster membership and ownership election.

Every Compressor unit is listed in ``units.json`` with a priority: 1 is the
home unit that should own the system whenever it is online, 2 is next in
line, and so on.  A unit owns the system (acts as host — runs the AI, the
integrations, and the scheduler) when no eligible unit ahead of it in that
list answers a health probe.  Otherwise it follows the highest-priority
unit that does answer.

Precedence is total and static, so no consensus protocol is needed: every
unit walks the same ordered list and independently reaches the same answer.
A returning higher-priority unit reclaims ownership because it finds nobody
ahead of it, while the stand-in sees it answering again and steps down.

"Eligible" means the unit can actually do the host's job — in practice that
it holds an Anthropic API key.  A unit that cannot host never promotes
itself, it just follows the best peer it can find.
"""

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
DEFAULT_PROBE_TIMEOUT = 2.0
DEFAULT_POLL_SECONDS = 15
# Consecutive probe rounds a peer ahead of us must miss before we take over.
# Stepping DOWN needs no confirmation — yielding to the rightful owner fast
# is always safe, whereas promoting on one dropped packet churns the whole
# host stack (Tuya connections, Spotify auth, scheduler) for nothing.
PROMOTE_AFTER_MISSES = 2


class ClusterError(Exception):
    pass


@dataclass(frozen=True)
class Unit:
    name: str
    priority: int
    host_ip: str
    host_port: int = DEFAULT_PORT


class UnitRegistry:
    """The tier list: every unit that may own the system, best first."""

    def __init__(self, units: list[Unit]):
        if not units:
            raise ClusterError("Unit registry is empty — list at least one unit.")

        by_name: dict[str, Unit] = {}
        by_priority: dict[int, Unit] = {}
        for unit in units:
            key = unit.name.casefold()
            if key in by_name:
                raise ClusterError(f"Duplicate unit name in registry: '{unit.name}'")
            if unit.priority in by_priority:
                other = by_priority[unit.priority]
                raise ClusterError(
                    f"Units '{other.name}' and '{unit.name}' share priority "
                    f"{unit.priority} — priorities must be unique so every unit "
                    "ranks the tier list identically."
                )
            by_name[key] = unit
            by_priority[unit.priority] = unit

        self._by_name = by_name
        self.units = tuple(sorted(units, key=lambda u: u.priority))

    @classmethod
    def load(cls, path: str = "units.json") -> "UnitRegistry":
        try:
            raw = json.loads(Path(path).read_text())
        except FileNotFoundError:
            raise
        except json.JSONDecodeError as e:
            raise ClusterError(f"{path} is not valid JSON: {e}") from e

        entries = raw.get("units") if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            raise ClusterError(f"{path} must hold a 'units' list.")

        units = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ClusterError(f"{path}: unit #{i + 1} is not an object.")
            missing = [k for k in ("name", "priority", "host_ip") if not entry.get(k)]
            if missing:
                raise ClusterError(
                    f"{path}: unit #{i + 1} is missing {', '.join(missing)}."
                )
            try:
                priority = int(entry["priority"])
            except (TypeError, ValueError):
                raise ClusterError(
                    f"{path}: unit '{entry['name']}' has a non-numeric priority."
                ) from None
            units.append(
                Unit(
                    name=str(entry["name"]),
                    priority=priority,
                    host_ip=str(entry["host_ip"]),
                    host_port=int(entry.get("host_port", DEFAULT_PORT)),
                )
            )
        return cls(units)

    def get(self, name: str) -> Unit:
        unit = self._by_name.get((name or "").casefold())
        if unit is None:
            known = ", ".join(f"'{u.name}'" for u in self.units)
            raise ClusterError(f"Unit '{name}' is not in the registry. Known units: {known}")
        return unit

    def ahead_of(self, unit: Unit) -> list[Unit]:
        """Units that outrank `unit`, best first."""
        return [u for u in self.units if u.priority < unit.priority]

    def others(self, unit: Unit) -> list[Unit]:
        """Every unit but `unit`, best first."""
        return [u for u in self.units if u.name != unit.name]


def probe(unit: Unit, timeout: float = DEFAULT_PROBE_TIMEOUT) -> bool:
    """True when `unit` is up AND currently claiming ownership.

    A unit that answers but reports ``owner: false`` is alive yet following
    someone else, which is not a reason to defer to it.
    """
    url = f"http://{unit.host_ip}:{unit.host_port}/health"
    try:
        data = httpx.get(url, timeout=timeout).json()
    except Exception:
        return False
    if not isinstance(data, dict) or not data.get("owner"):
        return False
    reported = str(data.get("unit_name", "")).casefold()
    if reported != unit.name.casefold():
        log.warning(
            "[Cluster] %s answered as '%s', not '%s' — check units.json against "
            "the name that unit was started with.",
            url, data.get("unit_name"), unit.name,
        )
        return False
    return True


class Coordinator:
    """Works out which unit owns the system, and keeps watching."""

    def __init__(
        self,
        registry: UnitRegistry,
        self_name: str,
        *,
        eligible: bool = True,
        prober: Callable[[Unit, float], bool] = probe,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
        promote_after_misses: int = PROMOTE_AFTER_MISSES,
    ):
        self.registry = registry
        self.unit = registry.get(self_name)
        self.eligible = eligible
        self._probe = prober
        self._poll_seconds = poll_seconds
        self._probe_timeout = probe_timeout
        self._promote_after_misses = max(1, promote_after_misses)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current: Optional[Unit] = None
        self._misses = 0

    @property
    def current_owner(self) -> Optional[Unit]:
        return self._current

    def decide(self) -> Optional[Unit]:
        """Return the unit that should own the system right now.

        That is this machine's own Unit when it should take over, a peer's
        Unit when it should follow, or None when nothing is reachable and
        this unit cannot host — the "alone and powerless" case, where the
        caller keeps relaying to the last known owner and hopes.
        """
        for peer in self.registry.ahead_of(self.unit):
            if self._probe(peer, self._probe_timeout):
                return peer
        if self.eligible:
            return self.unit
        # Not eligible: no self-promotion, so fall back to any owner at all,
        # including units ranked below us.
        for peer in self.registry.others(self.unit):
            if self._probe(peer, self._probe_timeout):
                return peer
        return None

    def start(self, on_change: Callable[[Optional[Unit]], None]) -> Optional[Unit]:
        """Decide immediately, then keep re-deciding on a background thread.

        Returns the initial owner. `on_change` fires only on later changes,
        so the caller applies the initial decision itself and is never
        called back before its own setup has finished.
        """
        self._current = self.decide()
        self._thread = threading.Thread(
            target=self._watch, args=(on_change,), daemon=True, name="ClusterCoordinator"
        )
        self._thread.start()
        return self._current

    def stop(self) -> None:
        self._stop.set()

    def _watch(self, on_change: Callable[[Optional[Unit]], None]) -> None:
        while not self._stop.wait(self._poll_seconds):
            self.run_round(on_change)

    def run_round(self, on_change: Callable[[Optional[Unit]], None]) -> Optional[Unit]:
        """One election round: re-decide and report a settled change.

        Never raises — a failed round leaves the current owner in place, so a
        transient network blip can't take the system down.
        """
        try:
            owner = self.decide()
        except Exception:
            log.exception("[Cluster] Election round failed; keeping current owner.")
            return self._current

        if owner == self._current:
            self._misses = 0
            return self._current

        if owner == self.unit:
            # Promotion only after the peers ahead of us have missed several
            # rounds in a row.
            self._misses += 1
            if self._misses < self._promote_after_misses:
                return self._current

        self._misses = 0
        self._current = owner
        try:
            on_change(owner)
        except Exception:
            log.exception("[Cluster] Owner-change handler failed.")
        return self._current
