"""Merriam-Webster's own Word of the Day, from its official RSS feed.

The feed lists about the last 10 days. Importing adds any of those words that aren't
in your list yet, so running it daily (e.g. from cron) grows the list on its own.
"""

from __future__ import annotations

from xml.etree import ElementTree

import httpx

from .errors import SourceError
from .models import unique

FEED_URL = "https://www.merriam-webster.com/wotd/feed/rss2"
FEED_NAME = "Merriam-Webster Word of the Day feed"


def fetch_feed_words(client: httpx.Client) -> list[str]:
    """The words in the feed, newest first."""
    try:
        response = client.get(FEED_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceError(f"{FEED_NAME}: request failed ({type(exc).__name__})") from exc
    return parse_feed(response.text)


def parse_feed(xml: str) -> list[str]:
    # Each <item>'s <title> is the word itself: <item><title>compendious</title>...
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise SourceError(f"{FEED_NAME}: not valid RSS ({exc})") from None
    return unique(item.findtext("title") or "" for item in root.iter("item"))
