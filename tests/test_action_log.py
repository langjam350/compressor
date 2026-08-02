import json


def test_configure_creates_log_directory(tmp_path):
    from src import action_log
    log_path = tmp_path / "nested" / "actions.txt"
    action_log.configure(str(log_path))
    assert log_path.parent.exists()


def test_log_query_writes_parseable_json_line(tmp_path):
    from src import action_log
    log_path = tmp_path / "actions.txt"
    action_log.configure(str(log_path))
    action_log.log_query("Kitchen", "turn on the lights")

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["unit"] == "Kitchen"
    assert record["event"] == "query"
    assert record["text"] == "turn on the lights"
    assert "ts" in record


def test_log_tool_call_writes_tool_fields(tmp_path):
    from src import action_log
    log_path = tmp_path / "actions.txt"
    action_log.configure(str(log_path))
    action_log.log_tool_call(
        "Kitchen", "control_tuya_device",
        {"device_name": "Lamp", "action": "on"}, "Lamp turned on.",
    )

    record = json.loads(log_path.read_text().strip().splitlines()[0])
    assert record["event"] == "tool_call"
    assert record["tool_name"] == "control_tuya_device"
    assert record["tool_input"] == {"device_name": "Lamp", "action": "on"}
    assert record["result"] == "Lamp turned on."


def test_log_wake_response_error_write_expected_events(tmp_path):
    from src import action_log
    log_path = tmp_path / "actions.txt"
    action_log.configure(str(log_path))
    action_log.log_wake("Kitchen")
    action_log.log_response("Kitchen", "Done.")
    action_log.log_error("Kitchen", "ai_ask", "boom")

    records = [json.loads(l) for l in log_path.read_text().strip().splitlines()]
    assert records[0]["event"] == "wake"
    assert records[1]["event"] == "response" and records[1]["text"] == "Done."
    assert records[2]["event"] == "error"
    assert records[2]["context"] == "ai_ask"
    assert records[2]["error"] == "boom"


def test_log_functions_do_nothing_before_configure():
    from src import action_log
    action_log._logger = None
    action_log.log_query("Kitchen", "hello")  # must not raise
