"""A small on-disk cache: one JSON file per looked-up word, e.g. cache/ephemeral.json."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import WordEntry

# Bump when the stored format changes; older files are then treated as misses.
CACHE_VERSION = 2  # 2: added etymology and first_known_use

log = logging.getLogger(__name__)


class JsonFileCache:
    def __init__(self, directory: str | Path, max_age: timedelta | None = timedelta(days=30)):
        """`max_age=None` keeps entries forever."""
        self.directory = Path(directory)
        self.max_age = max_age

    def get(self, word: str) -> WordEntry | None:
        path = self._path(word)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("version") != CACHE_VERSION or record.get("query") != word:
                return None
            expires_at = record.get("expires_at")
            if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                return None
            return WordEntry.from_dict(record["entry"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning("ignoring unreadable cache file %s (%s)", path, exc)
            return None

    def set(self, word: str, entry: WordEntry, max_age: timedelta | None = None) -> None:
        """Store `entry` for `word`. `max_age` overrides the cache default for this entry."""
        now = datetime.now(timezone.utc)
        age = max_age or self.max_age
        record = {
            "version": CACHE_VERSION,
            "query": word,
            "fetched_at": now.isoformat(),
            "expires_at": (now + age).isoformat() if age else None,
            "entry": entry.to_dict(),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        # Write to a temp file and rename, so a reader never sees a half-written file.
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path(word))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _path(self, word: str) -> Path:
        # Keep letters (including accented ones), digits and hyphens; "déjà vu" -> "déjà_vu".
        # Rare collisions ("a b" vs "a_b") are caught by the "query" check in get().
        name = re.sub(r"[^\w-]+", "_", word.casefold()).strip("_") or "_"
        return self.directory / f"{name}.json"
