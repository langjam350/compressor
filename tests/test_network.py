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
        timeout=15.0,
    )


def test_network_client_query_on_failure_returns_fallback(mocker):
    mocker.patch("src.network.client.httpx.post", side_effect=Exception("timeout"))

    from src.network.client import NetworkClient
    client = NetworkClient("192.168.1.100", 8765)
    result = client.query("Kitchen", "turn on the living room light")

    assert result == "Sorry, I can't reach the host right now."
