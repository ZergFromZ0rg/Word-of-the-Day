"""Datamuse (https://www.datamuse.com/api/): no key, synonyms and antonyms only.

It never supplies definitions, so it can fill gaps in an entry but never be the entry.
"""

from __future__ import annotations

from ..models import WordEntry, unique
from .base import MAX_RELATED_WORDS, DictionarySource

URL = "https://api.datamuse.com/words"


class DatamuseSource(DictionarySource):
    name = "Datamuse"
    provides = frozenset({"synonyms", "antonyms"})

    def lookup(self, word: str) -> WordEntry | None:
        synonyms = self._related(word, "rel_syn")
        antonyms = self._related(word, "rel_ant")
        if not synonyms and not antonyms:
            return None
        return WordEntry(word=word, senses=[], synonyms=synonyms, antonyms=antonyms, sources=[self.name])

    def _related(self, word: str, relation: str) -> list[str]:
        data = self.get_json(URL, params={relation: word, "max": str(MAX_RELATED_WORDS)})
        # Results are sorted by relevance: [{"word": "transient", "score": 49052}, ...]
        words = (item.get("word", "") for item in data or [] if isinstance(item, dict))
        return unique(words, exclude=[word], limit=MAX_RELATED_WORDS)
