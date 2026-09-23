"""Reading the word list and deciding which word belongs to which day.

The pick is deterministic: the same list, seed and date always give the same word,
so every process (CLI, web server, cron job) agrees on today's word without shared
state. Days are grouped into cycles as long as the list; each cycle is a fresh
shuffle, so every word appears exactly once per cycle and never two days running.
"""

from __future__ import annotations

import random
import re
from datetime import date
from pathlib import Path
from typing import Sequence

from .models import unique

DEFAULT_SEED = "word-of-the-day"


def load_words(path: str | Path) -> list[str]:
    """Read one word or phrase per line, skipping blanks, `#` comments and duplicates."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    words = (re.sub(r"\s+", " ", line.strip()) for line in lines)
    return unique(word for word in words if not word.startswith("#"))


def pick_word(words: Sequence[str], day: date, seed: str = DEFAULT_SEED) -> str:
    """Return the word for `day`."""
    if not words:
        raise ValueError("the word list is empty")
    cycle, position = divmod(day.toordinal(), len(words))
    return _cycle_order(words, cycle, seed)[position]


def _cycle_order(words: Sequence[str], cycle: int, seed: str) -> list[str]:
    if len(words) == 2:
        # The only way to never repeat is to alternate, so use the same order every cycle.
        return sorted(words, key=str.casefold)
    order = _shuffled(words, cycle, seed)
    # Avoid repeating yesterday's word when a new cycle starts. Only positions 0 and 1
    # move, so the previous cycle's last word is unaffected by its own fix-up.
    if len(order) > 2 and order[0] == _shuffled(words, cycle - 1, seed)[-1]:
        order[0], order[1] = order[1], order[0]
    return order


def _shuffled(words: Sequence[str], cycle: int, seed: str) -> list[str]:
    # Sorting first makes the result independent of the order of lines in the file.
    order = sorted(words, key=str.casefold)
    # A string seed is hashed with SHA-512, so it's stable across runs (unlike hash()).
    random.Random(f"{seed}:{cycle}").shuffle(order)
    return order
