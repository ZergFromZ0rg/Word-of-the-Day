"""Which word each day got, stored in a small JSON file (history.json by default).

Recording the pick is what makes a day's word stable: once today has a word, editing
words.txt doesn't change it. It also remembers words no dictionary could find, so
they're skipped from then on.

    {"version": 1,
     "days": {"2026-09-23": "perspicacious", "2026-09-24": "serendipity"},
     "not_found": ["qwzxvbn"]}
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HISTORY_VERSION = 1

log = logging.getLogger(__name__)


@dataclass
class History:
    days: dict[date, str] = field(default_factory=dict)
    not_found: set[str] = field(default_factory=set)  # casefolded

    @classmethod
    def load(cls, path: Path) -> History:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                days={date.fromisoformat(day): word for day, word in data.get("days", {}).items()},
                not_found=set(data.get("not_found", [])),
            )
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning("ignoring unreadable history file %s (%s)", path, exc)
            return cls()

    def save(self, path: Path) -> None:
        data = {
            "version": HISTORY_VERSION,
            "days": {day.isoformat(): word for day, word in sorted(self.days.items())},
            "not_found": sorted(self.not_found),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file and rename, so a reader never sees a half-written file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def before(self, day: date) -> list[tuple[date, str]]:
        """Recorded days earlier than `day`, most recent first."""
        return sorted(((d, w) for d, w in self.days.items() if d < day), reverse=True)
