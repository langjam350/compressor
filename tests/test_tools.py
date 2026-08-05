def test_tools_module_holds_all_schemas():
    from src.tools import TOOLS
    names = [t["name"] for t in TOOLS]
    assert names == ["control_tuya_device", "control_spotify", "open_program"]


def test_open_program_schema():
    from src.tools import TOOLS
    schema = next(t for t in TOOLS if t["name"] == "open_program")
    props = schema["input_schema"]["properties"]
    assert set(props) == {"program", "process", "argument"}
    assert schema["input_schema"]["required"] == ["program"]


def test_ai_client_module_has_no_tools_list():
    import src.ai_client as ai_client
    assert not hasattr(ai_client, "TOOLS")
