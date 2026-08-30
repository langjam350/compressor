from datetime import datetime

from src.scheduler import Scheduler

NOON = datetime(2026, 8, 29, 12, 0)


def test_register_records_the_task():
    sched = Scheduler()
    sched.register("tuya_sync", lambda: None, hour=0, minute=30)

    assert [(t.name, t.hour, t.minute) for t in sched._tasks] == [("tuya_sync", 0, 30)]


def test_fires_a_task_whose_time_has_passed_today():
    sched = Scheduler()
    sched.register("tuya_sync", lambda: None, hour=0)

    assert sched.fire_due(NOON) == ["tuya_sync"]


def test_does_not_fire_a_task_still_scheduled_for_later_today():
    sched = Scheduler()
    sched.register("evening_sync", lambda: None, hour=23)

    assert sched.fire_due(NOON) == []


def test_fires_a_task_at_most_once_per_day():
    sched = Scheduler()
    sched.register("tuya_sync", lambda: None, hour=0)

    assert sched.fire_due(NOON) == ["tuya_sync"]
    assert sched.fire_due(NOON.replace(hour=18)) == []


def test_fires_again_the_next_day():
    sched = Scheduler()
    sched.register("tuya_sync", lambda: None, hour=0)
    sched.fire_due(NOON)

    assert sched.fire_due(NOON.replace(day=30)) == ["tuya_sync"]


def test_a_late_start_still_runs_a_task_that_was_due_earlier():
    """Restarting at noon must not skip the midnight sync for that day."""
    sched = Scheduler()
    sched.register("tuya_sync", lambda: None, hour=0)

    assert sched.fire_due(NOON) == ["tuya_sync"]


def test_stop_ends_the_polling_loop():
    sched = Scheduler()
    sched.register("tuya_sync", lambda: None, hour=0)
    sched.stop()

    sched._loop()  # returns immediately instead of blocking on the interval

    assert sched._last_run == {}  # a stopped scheduler fires nothing


def test_run_task_swallows_exceptions():
    sched = Scheduler()

    def boom():
        raise RuntimeError("task exploded")

    sched.register("boom", boom, hour=0)
    sched._run_task(sched._tasks[0])  # must not raise
