"""
Background scheduler for periodic tasks.

Tasks are registered with a name, callable, and daily run time (hour, minute).
The scheduler loop checks every 30 seconds and fires any task whose scheduled
time has passed today but hasn't yet run today.  On first startup, if the
scheduled time has already passed today the task runs immediately so no sync
is skipped due to late restarts.
"""

import logging
import threading
import time
from datetime import date, datetime
from typing import Callable

log = logging.getLogger(__name__)


class _Task:
    def __init__(self, name: str, func: Callable, hour: int, minute: int):
        self.name = name
        self.func = func
        self.hour = hour
        self.minute = minute


class Scheduler:
    _CHECK_INTERVAL = 30  # seconds between polls

    def __init__(self):
        self._tasks: list[_Task] = []
        self._last_run: dict[str, date] = {}

    def register(self, name: str, func: Callable, hour: int, minute: int = 0) -> None:
        """Register a daily task.

        Args:
            name:   Unique identifier shown in logs.
            func:   Callable to invoke (runs in its own daemon thread).
            hour:   Hour of day to run (0-23, local time).
            minute: Minute of hour to run (default 0).
        """
        self._tasks.append(_Task(name, func, hour, minute))
        log.info("[Scheduler] Registered '%s' at %02d:%02d", name, hour, minute)

    def start(self) -> None:
        """Start the background polling loop."""
        t = threading.Thread(target=self._loop, daemon=True, name="Scheduler")
        t.start()

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            now = datetime.now()
            today = now.date()

            for task in self._tasks:
                scheduled = now.replace(
                    hour=task.hour, minute=task.minute, second=0, microsecond=0
                )
                already_ran = self._last_run.get(task.name) == today

                if now >= scheduled and not already_ran:
                    self._last_run[task.name] = today
                    log.info("[Scheduler] Firing task '%s'", task.name)
                    threading.Thread(
                        target=self._run_task,
                        args=(task,),
                        daemon=True,
                        name=f"Task-{task.name}",
                    ).start()

            time.sleep(self._CHECK_INTERVAL)

    def _run_task(self, task: _Task) -> None:
        try:
            task.func()
        except Exception:
            log.exception("[Scheduler] Task '%s' raised an exception.", task.name)
