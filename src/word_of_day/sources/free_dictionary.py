"""Free Dictionary API (https://dictionaryapi.dev): no key, Wiktionary-based data.

Returns a proper 404 for unknown words. The service is sometimes unavailable
(Cloudflare 522 after ~20s), which is why the HTTP client has a short timeout.
"""

from __future__ import annotations

from typing import Any

from ..models import Sense, WordEntry, unique
from .base import MAX_RELATED_WORDS, DictionarySource, url_path_word

URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"


class FreeDictionarySource(DictionarySource):
    name = "Free Dictionary API"

    def lookup(self, word: str) -> WordEntry | None:
        data = self.get_json(URL.format(word=url_path_word(word)))
        entry = parse_entries(data, word)
        if entry is not None:
            entry.sources = [self.name]
        return entry


def parse_entries(data: Any, word: str) -> WordEntry | None:
    """Combine the response's entries (one per etymology) into a single WordEntry."""
    if not isinstance(data, list):
        return None
    entries = [e for e in data if isinstance(e, dict)]

    senses: list[Sense] = []
    synonyms: list[str] = []
    antonyms: list[str] = []
    phonetics: list[dict[str, Any]] = []
    for entry in entries:
        phonetics += [p for p in entry.get("phonetics", []) if isinstance(p, dict)]
        for meaning in entry.get("meanings", []):
            part_of_speech = meaning.get("partOfSpeech") or None
            synonyms += meaning.get("synonyms", [])
            antonyms += meaning.get("antonyms", [])
            for definition in meaning.get("definitions", []):
                text = (definition.get("definition") or "").strip()
                example = (definition.get("example") or "").strip()
                if text:
                    senses.append(Sense(text, part_of_speech, [example] if example else []))
                synonyms += definition.get("synonyms", [])
                antonyms += definition.get("antonyms", [])

    if not senses:
        return None
    first = entries[0]
    head = first.get("word") or word
    pronunciation = first.get("phonetic") or next(
        (p["text"] for p in phonetics if p.get("text")), None
    )
    return WordEntry(
        word=head,
        senses=senses,
        synonyms=unique(synonyms, exclude=[head], limit=MAX_RELATED_WORDS),
        antonyms=unique(antonyms, exclude=[head], limit=MAX_RELATED_WORDS),
        pronunciation=pronunciation,
        audio_url=_pick_audio(phonetics),
        source_url=next(iter(first.get("sourceUrls") or []), None),
    )


def _pick_audio(phonetics: list[dict[str, Any]]) -> str | None:
    urls = [p["audio"] for p in phonetics if p.get("audio")]
    # Files are named like "ephemeral-us.mp3" / "ephemeral-uk.mp3"; prefer US.
    return next((u for u in urls if "-us." in u), None) or next(iter(urls), None)
