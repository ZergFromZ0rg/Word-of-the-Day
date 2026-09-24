import datetime as dt

import httpx
import pytest
from helpers import FIXTURES, Recorder

from word_of_day.errors import SourceError
from word_of_day.feed import FEED_URL, fetch_feed_words, parse_feed

FEED = (FIXTURES / "mw_wotd_feed.xml").read_text(encoding="utf-8")


def test_parse_feed_returns_words_newest_first():
    assert parse_feed(FEED) == ["compendious", "nemesis", "elegiac"]


def test_feed_items_have_dates():
    from word_of_day.feed import FeedItem, parse_feed_items

    items = parse_feed_items(FEED)
    assert items[0] == FeedItem("compendious", dt.date(2026, 9, 23))
    assert [i.day for i in items] == [
        dt.date(2026, 9, 23),
        dt.date(2026, 9, 22),
        dt.date(2026, 9, 21),
    ]
    undated = (
        "<rss><channel><item><title>x</title><link>https://e.com/x</link></item></channel></rss>"
    )
    assert parse_feed_items(undated) == [FeedItem("x", None)]


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
