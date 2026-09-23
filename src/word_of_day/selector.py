"""Reading the word list and choosing a word for a day.

Choosing is deterministic for a given list, history and date, so two processes
deciding at the same moment agree. The history (which date got which word) is
what keeps a day's word from changing when the list is edited; see history.py.
"""

from __future__ import annotations

import os
import random
import re
import tempfile
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path

from .models import unique

DEFAULT_SEED = "word-of-the-day"


def parse_words(text: str) -> list[str]:
    """One word or phrase per line, skipping blanks, `#` comments and duplicates."""
    words = (re.sub(r"\s+", " ", line.strip()) for line in text.splitlines())
    return unique(word for word in words if not word.startswith("#"))


def load_words(path: str | Path) -> list[str]:
    """Read a word list file (see parse_words)."""
    return parse_words(Path(path).read_text(encoding="utf-8"))


def save_words(path: str | Path, words: Iterable[str]) -> None:
    """Replace the word list file, all at once so a reader never sees half a list."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(words) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def add_words(path: str | Path, words: Iterable[str]) -> list[str]:
    """Append the words that aren't in the file yet. Returns the ones added."""
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    new = unique(words, exclude=load_words(path) if text else ())
    if new:
        separator = "\n" if text and not text.endswith("\n") else ""
        with path.open("a", encoding="utf-8") as f:
            f.write(separator + "\n".join(new) + "\n")
    return new


def choose_word(
    words: Sequence[str],
    history: Mapping[date, str],
    day: date,
    *,
    seed: str = DEFAULT_SEED,
    exclude: Collection[str] = (),
) -> str:
    """Pick a word for `day`, given the words already used on other days.

    Words that have never been used come first, in random order. Once every word
    has been used, it picks at random from the half of the list used longest ago,
    so recent words don't come back soon and the order differs each round.
    """
    excluded = {word.casefold() for word in exclude}
    # Sorting makes the result independent of the order of lines in the file.
    candidates = sorted((w for w in words if w.casefold() not in excluded), key=str.casefold)
    if not candidates:
        raise ValueError("there are no words to choose from")

    last_used: dict[str, date] = {}
    for used_on, word in history.items():
        if used_on != day:
            key = word.casefold()
            last_used[key] = max(used_on, last_used.get(key, used_on))

    # A string seed is hashed with SHA-512, so it's stable across runs (unlike hash()).
    rng = random.Random(f"{seed}:{day.isoformat()}")
    fresh = [w for w in candidates if w.casefold() not in last_used]
    if fresh:
        return rng.choice(fresh)
    oldest_first = sorted(candidates, key=lambda w: last_used[w.casefold()])
    return rng.choice(oldest_first[: max(1, len(oldest_first) // 2)])
