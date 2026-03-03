import pytest


def make_text_response(mocker, text: str):
    """Helper: mock a terminal Claude response with plain text."""
    block = mocker.Mock()
    block.type = "text"
    block.text = text
    response = mocker.Mock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def make_tool_response(mocker, tool_name: str, tool_input: dict, tool_id: str = "toolu_01"):
    """Helper: mock a Claude response that calls a tool."""
    block = mocker.Mock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    response = mocker.Mock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def test_ask_returns_text_on_plain_answer(mocker):
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    mock_create.return_value = make_text_response(mocker, "The universe is vast.")

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    result = client.ask("Tell me about space", lambda name, inp: "ok")

    assert result == "The universe is vast."


def test_ask_calls_tool_then_returns_text(mocker):
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    mock_create.side_effect = [
        make_tool_response(mocker, "control_tuya_device", {"device_name": "Living Room Light", "action": "on"}),
        make_text_response(mocker, "Living room light turned on."),
    ]

    tool_calls = []

    def handler(name, inp):
        tool_calls.append((name, inp))
        return "Living Room Light turned on"

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    result = client.ask("turn on the living room light", handler)

    assert len(tool_calls) == 1
    assert tool_calls[0][0] == "control_tuya_device"
    assert result == "Living room light turned on."


def test_ask_returns_fallback_on_empty_content(mocker):
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    response = mocker.Mock()
    response.stop_reason = "end_turn"
    response.content = []
    mock_create.return_value = response

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    result = client.ask("hello", lambda name, inp: "")

    assert result == "I couldn't generate a response."


# --- conversation history ---

def test_second_ask_includes_first_turn_in_context(mocker):
    """Second ask() call includes prior user and assistant turns in the messages list."""
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    mock_create.side_effect = [
        make_text_response(mocker, "The capital is Paris."),
        make_text_response(mocker, "France is in Western Europe."),
    ]

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    client.ask("What is the capital of France?", lambda n, i: "")
    client.ask("Where is that country?", lambda n, i: "")

    second_call_messages = mock_create.call_args_list[1][1]["messages"]
    # Should contain: user Q1, assistant A1, user Q2
    assert len(second_call_messages) == 3
    assert second_call_messages[0]["role"] == "user"
    assert second_call_messages[0]["content"] == "What is the capital of France?"
    assert second_call_messages[2]["role"] == "user"
    assert second_call_messages[2]["content"] == "Where is that country?"


def test_reset_clears_conversation_history(mocker):
    """After reset(), the next ask() starts a fresh thread with only the new message."""
    mock_anthropic = mocker.patch("src.ai_client.anthropic.Anthropic")
    mock_create = mock_anthropic.return_value.messages.create
    mock_create.side_effect = [
        make_text_response(mocker, "The capital is Paris."),
        make_text_response(mocker, "I don't know."),
    ]

    from src.ai_client import AIClient
    client = AIClient("fake-key", "You are an assistant.")
    client.ask("What is the capital of France?", lambda n, i: "")
    client.reset()
    client.ask("What is the capital of France?", lambda n, i: "")

    second_call_messages = mock_create.call_args_list[1][1]["messages"]
    assert len(second_call_messages) == 1
    assert second_call_messages[0]["content"] == "What is the capital of France?"
