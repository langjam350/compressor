import json

import pytest
from fastapi.testclient import TestClient


def test_info_endpoint_returns_location_keys(mocker):
    mocker.patch(
        "src.network.host_server.get_location",
        return_value={"city": "Chicago", "region": "Illinois", "country": "US", "timezone": "America/Chicago"}
    )
    from src.network.host_server import app
    client = TestClient(app)
    resp = client.get("/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "Chicago"
    assert data["timezone"] == "America/Chicago"


def test_info_endpoint_handles_geolocation_failure(mocker):
    mocker.patch(
        "src.network.host_server.get_location",
        side_effect=Exception("network error")
    )
    from src.network.host_server import app
    client = TestClient(app)
    resp = client.get("/info")
    assert resp.status_code == 200
    assert resp.json()["city"] == "Unknown"


def test_network_client_get_info(mocker):
    mock_get = mocker.patch("src.network.client.httpx.get")
    mock_get.return_value.json.return_value = {
        "city": "Chicago", "region": "Illinois", "country": "US", "timezone": "America/Chicago"
    }

    from src.network.client import NetworkClient
    client = NetworkClient("192.168.1.100", 8765)
    info = client.get_info()

    assert info["city"] == "Chicago"


def test_network_client_get_info_on_failure(mocker):
    mocker.patch("src.network.client.httpx.get", side_effect=Exception("timeout"))

    from src.network.client import NetworkClient
    client = NetworkClient("192.168.1.100", 8765)
    info = client.get_info()

    assert info == {}


def test_network_client_query_returns_response(mocker):
    mock_post = mocker.patch("src.network.client.httpx.post")
    mock_post.return_value.json.return_value = {"response": "Living Room Light turned on."}

    from src.network.client import NetworkClient
    client = NetworkClient("192.168.1.100", 8765)
    result = client.query("Kitchen", "turn on the living room light")

    assert result == "Living Room Light turned on."
    mock_post.assert_called_once_with(
        "http://192.168.1.100:8765/query",
        json={"unit_name": "Kitchen", "text": "turn on the living room light"},
        timeout=60.0,
    )


def test_network_client_query_on_failure_returns_fallback(mocker):
    mocker.patch("src.network.client.httpx.post", side_effect=Exception("timeout"))

    from src.network.client import NetworkClient
    client = NetworkClient("192.168.1.100", 8765)
    result = client.query("Kitchen", "turn on the living room light")

    assert result == "Sorry, I can't reach the host right now."


def test_health_reports_unit_name_and_ownership():
    from src.network.host_server import app
    app.state.unit_name = "Personal Laptop"
    app.state.owner = True
    app.state.priority = 2
    app.state.session_id = "abc123"
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {
        "unit_name": "Personal Laptop",
        "owner": True,
        "priority": 2,
        "session_id": "abc123",
        "connected_followers": 0,
    }


def test_health_counts_connected_followers_excluding_loopback():
    from unittest.mock import MagicMock
    from src.network.host_server import app, _connected_clients

    loopback = MagicMock()
    loopback.client = MagicMock(host="127.0.0.1")
    remote = MagicMock()
    remote.client = MagicMock(host="192.168.0.166")
    _connected_clients.extend([loopback, remote])

    try:
        client = TestClient(app)
        resp = client.get("/health")
    finally:
        _connected_clients.remove(loopback)
        _connected_clients.remove(remote)

    assert resp.json()["connected_followers"] == 1


def test_health_reports_a_follower_as_alive_but_not_owner():
    from src.network.host_server import app
    app.state.unit_name = "Personal Laptop"
    app.state.owner = False
    client = TestClient(app)

    assert client.get("/health").json()["owner"] is False


def test_set_host_repoints_http_and_websocket():
    from src.network.client import NetworkClient
    client = NetworkClient("192.168.0.100", 8765)

    assert client.set_host("192.168.0.166", 8765) is True
    assert client._base == "http://192.168.0.166:8765"
    assert client._ws_url == "ws://192.168.0.166:8765/ws"


def test_set_host_is_a_no_op_when_the_host_is_unchanged():
    from src.network.client import NetworkClient
    client = NetworkClient("192.168.0.100", 8765)

    assert client.set_host("192.168.0.100") is False


def test_set_host_closes_the_open_websocket_so_it_reconnects(mocker):
    from src.network.client import NetworkClient
    client = NetworkClient("192.168.0.100", 8765)
    client._ws = mocker.MagicMock()
    client._loop = mocker.MagicMock()
    run_coro = mocker.patch("src.network.client.asyncio.run_coroutine_threadsafe")

    client.set_host("192.168.0.166")

    run_coro.assert_called_once()
    client._ws.close.assert_called_once()


def test_query_endpoint_calls_query_handler_and_returns_result():
    from src.network.host_server import app
    app.state.query_handler = lambda unit_name, text: f"handled {unit_name}: {text}"
    client = TestClient(app)

    resp = client.post("/query", json={"unit_name": "Kitchen", "text": "turn on the lights"})

    assert resp.status_code == 200
    assert resp.json()["response"] == "handled Kitchen: turn on the lights"


def test_query_endpoint_returns_apology_when_handler_not_set():
    from src.network.host_server import app
    app.state.query_handler = None
    client = TestClient(app)

    resp = client.post("/query", json={"unit_name": "Kitchen", "text": "turn on the lights"})

    assert resp.status_code == 200
    assert "not ready" in resp.json()["response"]


def test_query_endpoint_catches_handler_exceptions():
    from src.network.host_server import app

    def boom(unit_name, text):
        raise RuntimeError("ai exploded")

    app.state.query_handler = boom
    client = TestClient(app)

    resp = client.post("/query", json={"unit_name": "Kitchen", "text": "turn on the lights"})

    assert resp.status_code == 200
    assert resp.json()["response"] == "Sorry, something went wrong."


def test_query_endpoint_coerces_non_string_result_to_string():
    from src.network.host_server import app

    def returns_none(unit_name, text):
        return None

    app.state.query_handler = returns_none
    client = TestClient(app)

    resp = client.post("/query", json={"unit_name": "Kitchen", "text": "turn on the lights"})

    assert resp.status_code == 200
    assert resp.json()["response"] == "Sorry, something went wrong."


def test_broadcast_endpoint_includes_local_handler_reply():
    from src.network.host_server import app
    app.state.unit_name = "Personal Desktop"
    app.state.broadcast_handler = lambda text: f"heard: {text}"
    client = TestClient(app)

    resp = client.post("/broadcast", json={"text": "dinner's ready", "timeout": 2.0})

    assert resp.status_code == 200
    data = resp.json()
    assert data["replies"] == [{"unit": "Personal Desktop", "text": "heard: dinner's ready"}]
    app.state.broadcast_handler = None


def test_broadcast_endpoint_ignores_local_handler_with_no_reply():
    from src.network.host_server import app
    app.state.unit_name = "Personal Desktop"
    app.state.broadcast_handler = lambda text: None
    client = TestClient(app)

    resp = client.post("/broadcast", json={"text": "anybody home", "timeout": 0.3})

    assert resp.status_code == 200
    assert resp.json()["replies"] == []
    app.state.broadcast_handler = None


def test_broadcast_endpoint_skips_the_hosts_own_loopback_connection():
    """A unit that owns the system points its own NetworkClient at
    127.0.0.1 (see Assistant._become_owner), so its self-loop WS
    connection shows up in _connected_clients too. /broadcast must not
    also push speak_request to it — the direct broadcast_handler call
    already covers the local unit, and double-delivery means it speaks
    (and can reply) twice for one request."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from src.network import host_server

    host_server.app.state.broadcast_handler = None
    loopback_client = MagicMock()
    loopback_client.client = MagicMock(host="127.0.0.1")
    loopback_client.send_text = AsyncMock()
    host_server._connected_clients.append(loopback_client)

    try:
        asyncio.run(host_server.broadcast_endpoint(
            host_server.BroadcastRequest(text="hello", timeout=0.2)
        ))
    finally:
        host_server._connected_clients.remove(loopback_client)

    loopback_client.send_text.assert_not_called()


def test_broadcast_endpoint_sends_to_non_loopback_clients():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from src.network import host_server

    host_server.app.state.broadcast_handler = None
    remote_client = MagicMock()
    remote_client.client = MagicMock(host="192.168.0.166")
    remote_client.send_text = AsyncMock()
    host_server._connected_clients.append(remote_client)

    try:
        asyncio.run(host_server.broadcast_endpoint(
            host_server.BroadcastRequest(text="hello", timeout=0.2)
        ))
    finally:
        host_server._connected_clients.remove(remote_client)

    remote_client.send_text.assert_called_once()


def test_broadcast_endpoint_reaps_a_dead_connection_on_send_failure():
    """A stale connection (e.g. the follower's machine slept, or the TCP
    link died without a clean WebSocketDisconnect) stays in
    _connected_clients, so /health's connected_followers keeps counting it
    as alive. Before this fix, a failed send_text was silently swallowed
    and the dead client was never removed — every future /broadcast would
    also silently fail against it, forever, with no error anywhere."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from src.network import host_server

    host_server.app.state.broadcast_handler = None
    dead_client = MagicMock()
    dead_client.client = MagicMock(host="192.168.0.166")
    dead_client.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))
    host_server._connected_clients.append(dead_client)

    try:
        asyncio.run(host_server.broadcast_endpoint(
            host_server.BroadcastRequest(text="hello", timeout=0.2)
        ))
        assert dead_client not in host_server._connected_clients
    finally:
        if dead_client in host_server._connected_clients:
            host_server._connected_clients.remove(dead_client)


def test_broadcast_endpoint_times_out_with_no_handler_and_no_clients():
    from src.network.host_server import app
    app.state.broadcast_handler = None
    client = TestClient(app)

    resp = client.post("/broadcast", json={"text": "hello house", "timeout": 0.2})

    assert resp.status_code == 200
    assert resp.json()["replies"] == []


def test_route_speak_response_delivers_to_matching_pending_queue():
    import asyncio
    from src.network import host_server

    async def run():
        queue = asyncio.Queue()
        host_server._pending_broadcasts["req-1"] = queue
        try:
            handled = await host_server._route_speak_response(json.dumps({
                "type": "speak_response",
                "request_id": "req-1",
                "unit": "Personal Laptop",
                "text": "I'm here",
            }))
            assert handled is True
            assert queue.get_nowait() == {"unit": "Personal Laptop", "text": "I'm here"}
        finally:
            host_server._pending_broadcasts.pop("req-1", None)

    asyncio.run(run())


def test_route_speak_response_ignores_other_message_types():
    import asyncio
    from src.network import host_server

    async def run():
        handled = await host_server._route_speak_response(json.dumps({
            "type": "spotify", "action": "play",
        }))
        assert handled is False

    asyncio.run(run())


def test_route_speak_response_ignores_unparseable_message():
    import asyncio
    from src.network import host_server

    async def run():
        handled = await host_server._route_speak_response("not json")
        assert handled is False

    asyncio.run(run())
