def test_tools_module_holds_existing_schemas():
    from src.tools import TOOLS
    names = [t["name"] for t in TOOLS]
    assert names == ["control_tuya_device", "control_spotify"]


def test_ai_client_module_has_no_tools_list():
    import src.ai_client as ai_client
    assert not hasattr(ai_client, "TOOLS")
