"""Plain-text rendering of a WordEntry for the terminal."""

from __future__ import annotations

import textwrap
from datetime import date

from .models import Sense, WordEntry

WIDTH = 78


def format_entry(
    entry: WordEntry,
    *,
    day: date | None = None,
    senses_per_part: int = 3,
    related_limit: int = 8,
) -> str:
    lines = []
    if day is not None:
        title = f"WORD OF THE DAY · {day:%A, %B} {day.day}, {day.year}"
        lines += [title, "=" * len(title), ""]
    lines.append(f"{entry.word}  {entry.pronunciation}" if entry.pronunciation else entry.word)

    for part_of_speech, senses in _group_by_part_of_speech(entry.senses).items():
        lines += ["", part_of_speech or "definition"]
        for number, sense in enumerate(senses[:senses_per_part], start=1):
            lines += _wrap(f"{number}. {sense.definition}", indent="  ", hanging="     ")
            for example in sense.examples[:1]:
                lines += _wrap(f"“{example}”", indent="     ", hanging="      ")
        if len(senses) > senses_per_part:
            lines.append(f"  … {len(senses) - senses_per_part} more")

    history = [("Origin", entry.etymology), ("First known use", entry.first_known_use)]
    history = [(label, text) for label, text in history if text]
    if history:
        lines.append("")
    for label, text in history:
        lines += _wrap(f"{label}: {text}", hanging=" " * (len(label) + 2))

    related = [("Synonyms", entry.synonyms), ("Antonyms", entry.antonyms)]
    related = [(label, words) for label, words in related if words]
    if related:
        lines.append("")
    for label, words in related:
        lines += _wrap(f"{label}: " + ", ".join(words[:related_limit]), hanging=" " * 10)

    lines += ["", "Source: " + ", ".join(entry.sources)]
    if entry.source_url:
        lines.append(entry.source_url)
    return "\n".join(lines)


def _group_by_part_of_speech(senses: list[Sense]) -> dict[str | None, list[Sense]]:
    groups: dict[str | None, list[Sense]] = {}
    for sense in senses:
        groups.setdefault(sense.part_of_speech, []).append(sense)
    return groups


def _wrap(text: str, indent: str = "", hanging: str = "") -> list[str]:
    return textwrap.wrap(
        text, width=WIDTH, initial_indent=indent, subsequent_indent=hanging or indent
    ) or [indent]
