import pytest

from src.integrations.youtube import YouTubeSearcher


def _mock_ydl(mocker, info):
    """Patch yt_dlp so YoutubeDL(...).__enter__().extract_info() returns info."""
    mock_yt = mocker.patch("src.integrations.youtube.yt_dlp")
    ydl = mock_yt.YoutubeDL.return_value.__enter__.return_value
    ydl.extract_info.return_value = info
    return ydl


# --------------------------------------------------------------------- #
# Channel-default word list                                              #
# --------------------------------------------------------------------- #

def test_channel_for_matches_whole_words_only():
    yt = YouTubeSearcher({"lofi": "@LofiGirl"})
    assert yt.channel_for("play some lofi beats") == "@LofiGirl"
    assert yt.channel_for("play LOFI") == "@LofiGirl"          # case-insensitive
    assert yt.channel_for("play lofidelity records") is None    # substring != word


def test_resolve_uses_latest_upload_for_channel_word(mocker):
    ydl = _mock_ydl(mocker, {"entries": [{"id": "vid1", "title": "Newest Video"}]})
    yt = YouTubeSearcher({"sermon": "https://www.youtube.com/@SomeChurch"})

    result = yt.resolve("play this week's sermon")

    ydl.extract_info.assert_called_once_with(
        "https://www.youtube.com/@SomeChurch/videos", download=False
    )
    assert result == {
        "title": "Newest Video",
        "url": "https://www.youtube.com/watch?v=vid1",
        "channel": "",
    }


def test_resolve_falls_back_to_search_without_channel_word(mocker):
    ydl = _mock_ydl(mocker, {"entries": [{"id": "abc", "title": "Some Song", "channel": "Uploader"}]})
    yt = YouTubeSearcher({"lofi": "@LofiGirl"})

    result = yt.resolve("obscure remix nobody put on spotify")

    ydl.extract_info.assert_called_once_with(
        "ytsearch1:obscure remix nobody put on spotify", download=False
    )
    assert result["url"] == "https://www.youtube.com/watch?v=abc"
    assert result["channel"] == "Uploader"


def test_resolve_falls_back_to_search_when_channel_lookup_fails(mocker):
    ydl = _mock_ydl(mocker, None)
    ydl.extract_info.side_effect = [
        RuntimeError("channel gone"),
        {"entries": [{"id": "xyz", "title": "Found Anyway"}]},
    ]
    yt = YouTubeSearcher({"lofi": "@Deleted"})

    result = yt.resolve("play lofi")

    assert ydl.extract_info.call_count == 2
    assert result["title"] == "Found Anyway"


# --------------------------------------------------------------------- #
# Channel URL normalization                                              #
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("channel,expected", [
    ("@LofiGirl", "https://www.youtube.com/@LofiGirl/videos"),
    ("LofiGirl", "https://www.youtube.com/@LofiGirl/videos"),
    ("Lofi Girl", "https://www.youtube.com/@LofiGirl/videos"),
    ("https://www.youtube.com/@SomeChurch", "https://www.youtube.com/@SomeChurch/videos"),
    ("https://www.youtube.com/@SomeChurch/videos", "https://www.youtube.com/@SomeChurch/videos"),
])
def test_channel_videos_url(channel, expected):
    assert YouTubeSearcher._channel_videos_url(channel) == expected


# --------------------------------------------------------------------- #
# Defensive behavior                                                     #
# --------------------------------------------------------------------- #

def test_lookup_errors_return_none(mocker):
    ydl = _mock_ydl(mocker, None)
    ydl.extract_info.side_effect = RuntimeError("network down")
    yt = YouTubeSearcher()
    assert yt.search("anything") is None


def test_empty_results_return_none(mocker):
    _mock_ydl(mocker, {"entries": []})
    yt = YouTubeSearcher()
    assert yt.search("anything") is None


def test_missing_yt_dlp_disables_searcher(mocker):
    mocker.patch("src.integrations.youtube.yt_dlp", None)
    yt = YouTubeSearcher({"lofi": "@LofiGirl"})
    assert YouTubeSearcher.available() is False
    assert yt.resolve("play lofi") is None
