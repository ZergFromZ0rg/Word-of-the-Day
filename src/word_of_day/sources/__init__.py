"""Dictionary sources. Each one turns a different API's JSON into a WordEntry."""

from __future__ import annotations

import httpx

from .base import DictionarySource
from .datamuse import DatamuseSource
from .free_dictionary import FreeDictionarySource
from .merriam_webster import MerriamWebsterSource
from .wiktionary import WiktionarySource

__all__ = [
    "DatamuseSource",
    "DictionarySource",
    "FreeDictionarySource",
    "MerriamWebsterSource",
    "WiktionarySource",
    "default_sources",
]


def default_sources(
    client: httpx.Client,
    *,
    mw_dictionary_key: str | None = None,
    mw_thesaurus_key: str | None = None,
) -> list[DictionarySource]:
    """Sources in priority order. Merriam-Webster is included only when a key is given."""
    sources: list[DictionarySource] = []
    if mw_dictionary_key:
        sources.append(MerriamWebsterSource(client, mw_dictionary_key, mw_thesaurus_key or None))
    sources += [FreeDictionarySource(client), WiktionarySource(client), DatamuseSource(client)]
    return sources
