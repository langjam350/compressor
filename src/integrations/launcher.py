import os
from pathlib import Path

import psutil
import yaml

# from src import action_log  # enabled in learning task


class ProgramLauncher:
    """Opens configured programs, resolving program -> process trees.

    Never raises: every path returns a human-sensible result string
    (same defensive contract as TuyaController._safe_control).
    """

    def __init__(
        self,
        programs: list[dict],
        learned_path: str = "programs_learned.yaml",
        unit_name: str = "host",
    ):
        # name (lowercased) -> program entry
        self._programs = {p["name"].lower(): p for p in programs}
        self._learned_path = Path(learned_path)
        self._unit_name = unit_name
        self._learned = self._load_learned()

    # ------------------------------------------------------------------ #
    # Matching                                                            #
    # ------------------------------------------------------------------ #

    def _match(self, spoken: str) -> dict | None:
        key = spoken.strip().lower()
        if key in self._programs:
            return self._programs[key]
        for entry in self._programs.values():
            if key in [a.lower() for a in entry.get("aliases", [])]:
                return entry
        for name, entry in self._programs.items():
            if key in name or name in key:
                return entry
        return None

    def _resolve_process(self, program_name: str, entry: dict, process: str | None) -> str | None:
        """Tree lookup: config.yaml processes win over learned ones."""
        if not process:
            return None
        p = process.strip().lower()
        configured = {k.lower(): v for k, v in (entry.get("processes") or {}).items()}
        if p in configured:
            return configured[p]
        learned = {k.lower(): v for k, v in self._learned.get(program_name, {}).items()}
        return learned.get(p)

    def _is_running(self, process_name: str) -> bool:
        target = process_name.lower()
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name == target or name == target + ".exe":
                return True
        return False

    # ------------------------------------------------------------------ #
    # Learned-tree persistence (extended in the learning task)            #
    # ------------------------------------------------------------------ #

    def _load_learned(self) -> dict:
        if not self._learned_path.exists():
            return {}
        try:
            data = yaml.safe_load(self._learned_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[Launcher] Could not read {self._learned_path} ({e}) — treating as empty.")
            return {}

    def _learn(self, program_name: str, process: str, argument: str) -> None:
        self._learned.setdefault(program_name, {})[process] = argument
        try:
            self._learned_path.write_text(
                yaml.dump(self._learned, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[Launcher] Could not write {self._learned_path} ({e}).")
        # action_log.log_process_learned(self._unit_name, program_name, process, argument)  # enabled in learning task

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def open(self, program: str, process: str | None = None, argument: str | None = None) -> str:
        try:
            entry = self._match(program)
            if entry is None:
                return f"Program '{program}' isn't configured on {self._unit_name}."
            name = entry["name"]

            tree_argument = self._resolve_process(name, entry, process)
            final_argument = tree_argument if tree_argument is not None else argument
            is_new_process = bool(process) and tree_argument is None and argument is not None

            if final_argument is None:
                if self._is_running(entry.get("process_name", "")):
                    return f"{name} is already running."
                os.startfile(entry["launch"])
                return f"Opening {name}."

            os.startfile(entry["launch"], arguments=final_argument)
            if is_new_process:
                self._learn(name, process.strip().lower(), argument)
            if process:
                return f"Opening {process.strip().lower()} in {name}."
            return f"Opening {name}."
        except Exception as e:
            return f"Couldn't open {program} ({e})."
