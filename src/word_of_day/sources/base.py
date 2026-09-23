"""The interface every dictionary source implements, plus shared HTTP handling."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

import httpx

from ..errors import SourceError
from ..models import FILLABLE_FIELDS, WordEntry

# Cap on synonyms/antonyms kept per source. Thesauruses can return hundreds for
# common words; the first ones are the most relevant.
MAX_RELATED_WORDS = 20


class DictionarySource(ABC):
    """Looks words up in one dictionary and converts the result to a WordEntry."""

    name: str
    # Which WordEntry fields this source can supply. The service uses it to skip
    # sources that couldn't fill whatever the main entry is still missing.
    provides: frozenset[str] = frozenset({"senses", *FILLABLE_FIELDS})

    def __init__(self, client: httpx.Client):
        self.client = client

    @abstractmethod
    def lookup(self, word: str) -> WordEntry | None:
        """Return the entry, or None if this dictionary doesn't know the word.

        Raises SourceError when the dictionary can't be asked (network, auth, limits).
        An entry with no senses is allowed: it means the source only knows related
        words (a thesaurus), which can fill gaps but never be the main entry.
        """

    def get_json(self, url: str, params: dict[str, str] | None = None) -> Any | None:
        """GET a JSON document. Returns None on 404; raises SourceError on other failures."""
        try:
            response = self.client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"{self.name}: request failed ({type(exc).__name__})") from exc

        status = response.status_code
        if status == 404:
            return None
        if status in (401, 403):
            raise SourceError(f"{self.name}: request was refused (HTTP {status}), check the API key")
        if status == 429:
            raise SourceError(f"{self.name}: rate limit reached (HTTP 429)")
        if response.is_error:
            raise SourceError(f"{self.name}: server error (HTTP {status})")

        try:
            return response.json()
        except ValueError:
            snippet = response.text.strip()[:120]
            raise SourceError(f"{self.name}: expected JSON but got {snippet!r}") from None


def url_path_word(word: str) -> str:
    """Encode a word for use as a URL path segment ("déjà vu" -> "d%C3%A9j%C3%A0%20vu")."""
    return quote(word, safe="")
