import httpx
import pytest
from helpers import FIXTURES, Recorder

from word_of_day.errors import SourceError
from word_of_day.feed import FEED_URL, fetch_feed_words, parse_feed

FEED = (FIXTURES / "mw_wotd_feed.xml").read_text(encoding="utf-8")


def test_parse_feed_returns_words_newest_first():
    assert parse_feed(FEED) == ["compendious", "nemesis", "elegiac"]


def test_fetch_feed_words():
    api = Recorder(lambda request: httpx.Response(200, text=FEED))
    assert fetch_feed_words(api.client()) == ["compendious", "nemesis", "elegiac"]
    assert str(api.requests[0].url) == FEED_URL


def test_feed_errors_are_source_errors():
    with pytest.raises(SourceError, match="not valid RSS"):
        parse_feed("<html>maintenance</html")
    api = Recorder(lambda request: httpx.Response(503))
    with pytest.raises(SourceError, match="request failed"):
        fetch_feed_words(api.client())
