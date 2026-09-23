"""Wiktionary's REST definition endpoint: no key, reliable, definitions and examples only.

Definitions come back as HTML snippets. A definition with sub-senses also contains
them as a nested <ol>, and they're listed again separately, so the nested list is cut.
Content is CC BY-SA: keep the source name and link when displaying it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from ..models import Sense, WordEntry, unique
from .base import DictionarySource, url_path_word

URL = "https://en.wiktionary.org/api/rest_v1/page/definition/{word}"
PAGE_URL = "https://en.wiktionary.org/wiki/{word}"


class WiktionarySource(DictionarySource):
    name = "Wiktionary"
    provides = frozenset({"senses"})

    def lookup(self, word: str) -> WordEntry | None:
        # Page titles are case-sensitive ("Easter" vs "easter"), so retry in lowercase.
        for title in dict.fromkeys([word, word.lower()]):
            data = self.get_json(URL.format(word=url_path_word(title)))
            senses = parse_definitions(data)
            if senses:
                return WordEntry(
                    word=title,
                    senses=senses,
                    source_url=PAGE_URL.format(word=url_path_word(title)),
                    sources=[self.name],
                )
        return None


def parse_definitions(data: Any) -> list[Sense]:
    if not isinstance(data, dict):
        return []
    senses = []
    for usage in data.get("en", []):
        if usage.get("language", "English") != "English":
            continue
        part_of_speech = (usage.get("partOfSpeech") or "").lower() or None
        for definition in usage.get("definitions", []):
            html = re.split(r"<(?:ol|ul|dl)\b", definition.get("definition", ""), maxsplit=1)[0]
            text = html_to_text(html)
            if text:
                senses.append(Sense(text, part_of_speech, _examples(definition)))
    return senses


def _examples(definition: dict[str, Any]) -> list[str]:
    parsed = [
        e.get("example", "") for e in definition.get("parsedExamples", []) if isinstance(e, dict)
    ]
    raw = parsed or definition.get("examples", [])
    return unique(html_to_text(example) for example in raw)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("style", "script"):
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script") and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()
