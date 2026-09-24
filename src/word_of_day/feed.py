"""Merriam-Webster's own Word of the Day, from its official RSS feed.

The feed lists about the last 10 days. Importing adds any of those words that aren't
in your list yet, so running it daily (e.g. from cron) grows the list on its own.
"""

from __future__ import annotations

import re
from datetime import date
from typing import NamedTuple
from xml.etree import ElementTree

import httpx

from .errors import SourceError
from .models import unique

FEED_URL = "https://www.merriam-webster.com/wotd/feed/rss2"
FEED_NAME = "Merriam-Webster Word of the Day feed"


class FeedItem(NamedTuple):
    word: str
    day: date | None  # the day Merriam-Webster features it, if the link says


def fetch_feed_items(client: httpx.Client) -> list[FeedItem]:
    """The feed's words with their dates, newest first."""
    try:
        response = client.get(FEED_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceError(f"{FEED_NAME}: request failed ({type(exc).__name__})") from exc
    return parse_feed_items(response.text)


def fetch_feed_words(client: httpx.Client) -> list[str]:
    """The words in the feed, newest first."""
    return unique(item.word for item in fetch_feed_items(client))


def parse_feed_items(xml: str) -> list[FeedItem]:
    # <item><title>compendious</title>
    #       <link>https://www.merriam-webster.com/word-of-the-day/compendious-2026-09-23</link>
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise SourceError(f"{FEED_NAME}: not valid RSS ({exc})") from None
    items = []
    for item in root.iter("item"):
        word = (item.findtext("title") or "").strip()
        match = re.search(r"(\d{4}-\d{2}-\d{2})/?$", (item.findtext("link") or "").strip())
        if word:
            items.append(FeedItem(word, date.fromisoformat(match[1]) if match else None))
    return items


def parse_feed(xml: str) -> list[str]:
    return unique(item.word for item in parse_feed_items(xml))
