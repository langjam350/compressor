def test_build_system_prompt_includes_location_and_devices():
    from src.assistant import build_system_prompt
    prompt = build_system_prompt(
        {"city": "Chicago", "region": "Illinois", "timezone": "America/Chicago"},
        [{"name": "Living Room Light"}, {"name": "Bedroom Fan"}]
    )
    assert "Chicago" in prompt
    assert "Living Room Light" in prompt
    assert "Bedroom Fan" in prompt
