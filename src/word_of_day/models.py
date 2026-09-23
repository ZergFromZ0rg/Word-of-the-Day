"""The data shapes every dictionary source is converted into."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

# Fields that can be filled in from a second source when the first one left them empty.
# Senses are never mixed between sources, since numbering and wording wouldn't line up.
FILLABLE_FIELDS = ("synonyms", "antonyms", "pronunciation", "audio_url")


@dataclass
class Sense:
    """One meaning of a word, e.g. 'lasting a very short time' (adjective)."""

    definition: str
    part_of_speech: str | None = None
    examples: list[str] = field(default_factory=list)


@dataclass
class WordEntry:
    """Everything we know about a word, normalized across dictionaries."""

    word: str
    senses: list[Sense]
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    pronunciation: str | None = None
    audio_url: str | None = None
    # Word history, e.g. "Greek ephēmeros lasting a day, from epi- + hēmera day".
    # Like senses, these belong to the dictionary that supplied the entry.
    etymology: str | None = None
    first_known_use: str | None = None  # e.g. "1576", "15th century"
    source_url: str | None = None
    sources: list[str] = field(default_factory=list)

    @property
    def definition(self) -> str | None:
        """The first (usually most common) definition."""
        return self.senses[0].definition if self.senses else None

    @property
    def parts_of_speech(self) -> list[str]:
        return unique(s.part_of_speech for s in self.senses if s.part_of_speech)

    @property
    def examples(self) -> list[str]:
        return [example for sense in self.senses for example in sense.examples]

    def missing_fields(self) -> list[str]:
        return [name for name in FILLABLE_FIELDS if not getattr(self, name)]

    def fill_missing_from(self, other: WordEntry) -> WordEntry:
        """Return a copy with empty fillable fields taken from `other`."""
        updates = {
            name: getattr(other, name) for name in self.missing_fields() if getattr(other, name)
        }
        if not updates:
            return self
        return replace(self, **updates, sources=unique([*self.sources, *other.sources]))

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-serializable dict, e.g. for an API response or the cache."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WordEntry:
        return cls(
            word=data["word"],
            senses=[Sense(**sense) for sense in data.get("senses", [])],
            synonyms=list(data.get("synonyms", [])),
            antonyms=list(data.get("antonyms", [])),
            pronunciation=data.get("pronunciation"),
            audio_url=data.get("audio_url"),
            etymology=data.get("etymology"),
            first_known_use=data.get("first_known_use"),
            source_url=data.get("source_url"),
            sources=list(data.get("sources", [])),
        )


def unique(
    items: Iterable[str], *, exclude: Iterable[str] = (), limit: int | None = None
) -> list[str]:
    """Drop blanks and case-insensitive duplicates, keeping the first spelling and order."""
    seen = {item.casefold() for item in exclude}
    result = []
    for item in items:
        item = item.strip()
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if limit is not None and len(result) >= limit:
            break
    return result
