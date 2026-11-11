import pytest

from src import action_log


@pytest.fixture(autouse=True)
def _reset_action_log(tmp_path):
    """Point the action log at a throwaway file before every test.

    Assistant.__init__ calls action_log.configure() with no args (the
    production "logs/actions.txt" default) unconditionally, regardless of
    role. A test that builds a real Assistant() without mocking that call
    repoints the module-level logger at the real log for the rest of the
    test session — and a later, unmocked log_* call then writes real
    entries into it. (Confirmed: this is how fixture data like "Kitchen",
    "TestUnit", and "task one"/"task two" ended up in the production log.)
    This is a safety net on top of each test helper mocking
    action_log.configure itself — it only resets the starting point, so it
    doesn't interfere with tests/test_action_log.py's own direct,
    explicit-path tests of the real configure()/log_* functions.
    """
    action_log.configure(str(tmp_path / "test-actions.txt"))
