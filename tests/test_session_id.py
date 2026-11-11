from src.session_id import generate_session_id


def test_generate_session_id_returns_nonempty_hex_string():
    session_id = generate_session_id()
    assert isinstance(session_id, str)
    assert len(session_id) == 16
    int(session_id, 16)  # raises if not valid hex


def test_generate_session_id_is_unique_across_calls():
    ids = {generate_session_id() for _ in range(100)}
    assert len(ids) == 100
