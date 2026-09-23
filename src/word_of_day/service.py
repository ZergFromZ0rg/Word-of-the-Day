"""WordOfTheDay: ties the word list, dictionary sources and cache together."""

from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Mapping

import httpx

from . import __version__
from .cache import JsonFileCache
from .errors import LookupFailedError, SourceError, WordNotFoundError, WordOfTheDayError
from .models import WordEntry
from .selector import DEFAULT_SEED, load_words, pick_word
from .sources import DictionarySource, default_sources

USER_AGENT = f"word-of-the-day/{__version__} (+https://github.com/ZergFromZ0rg/Word-of-the-Day)"
# Short enough that a dictionary that's down doesn't stall a page load for long.
HTTP_TIMEOUT = 8.0
# Entries assembled while a source was failing are re-fetched sooner than usual.
DEGRADED_CACHE_AGE = timedelta(days=1)
# After a source fails, skip it for this long instead of waiting on it for every word.
SOURCE_COOLDOWN = timedelta(minutes=5)

log = logging.getLogger(__name__)


class WordOfTheDay:
    """
    >>> with WordOfTheDay.from_env("words.txt") as wotd:
    ...     entry = wotd.today()
    ...     print(entry.word, entry.definition)
    """

    def __init__(
        self,
        words_file: str | Path,
        sources: Iterable[DictionarySource],
        cache: JsonFileCache | None = None,
        *,
        seed: str = DEFAULT_SEED,
        client: httpx.Client | None = None,
        source_cooldown: timedelta = SOURCE_COOLDOWN,
    ):
        """Wire things up explicitly. `client`, if given, is closed by close()."""
        self.words_file = Path(words_file)
        self.sources = list(sources)
        self.cache = cache
        self.seed = seed
        self.source_cooldown = source_cooldown
        self._client = client
        self._cooling_down: dict[DictionarySource, float] = {}  # source -> monotonic deadline

    @classmethod
    def from_env(
        cls,
        words_file: str | Path = "words.txt",
        cache_dir: str | Path | None = "cache",
        *,
        env: Mapping[str, str] | None = None,
        seed: str = DEFAULT_SEED,
    ) -> WordOfTheDay:
        """Build with the default sources, reading API keys from the environment.

        Uses MW_DICTIONARY_KEY and MW_THESAURUS_KEY if set. Pass cache_dir=None to
        disable caching. This doesn't read .env files; the CLI does that itself.
        """
        env = os.environ if env is None else env
        client = httpx.Client(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        sources = default_sources(
            client,
            mw_dictionary_key=env.get("MW_DICTIONARY_KEY"),
            mw_thesaurus_key=env.get("MW_THESAURUS_KEY"),
        )
        cache = JsonFileCache(cache_dir) if cache_dir is not None else None
        return cls(words_file, sources, cache, seed=seed, client=client)

    # --- Selection (no network) ---

    def words(self) -> list[str]:
        """The word list, re-read on every call so edits apply without a restart."""
        words = load_words(self.words_file)
        if not words:
            raise WordOfTheDayError(f"{self.words_file} doesn't contain any words")
        return words

    def word_for(self, day: date | None = None) -> str:
        """The word picked for `day` (default: today, in the machine's local time zone)."""
        return pick_word(self.words(), day or date.today(), self.seed)

    # --- Lookup ---

    def today(self, *, refresh: bool = False) -> WordEntry:
        return self.for_date(date.today(), refresh=refresh)

    def for_date(self, day: date, *, refresh: bool = False) -> WordEntry:
        return self.lookup(self.word_for(day), refresh=refresh)

    def lookup(self, word: str, *, refresh: bool = False) -> WordEntry:
        """Look up any word, using the cache unless `refresh` is set.

        Raises WordNotFoundError if no dictionary knows the word, or
        LookupFailedError if sources failed and none of the others found it.
        """
        if self.cache and not refresh:
            cached = self.cache.get(word)
            if cached is not None:
                log.debug("cache hit for %r", word)
                return cached

        entry, errors = self._fetch(word)
        if self.cache:
            self.cache.set(word, entry, max_age=DEGRADED_CACHE_AGE if errors else None)
        return entry

    def _fetch(self, word: str) -> tuple[WordEntry, list[SourceError]]:
        """Ask sources in priority order.

        The first source with definitions supplies the entry. Later sources are only
        asked if the entry is still missing something they can provide (synonyms,
        pronunciation...), and only fill those empty fields.
        """
        entry: WordEntry | None = None
        early_extras: list[WordEntry] = []  # e.g. synonyms found before any definitions
        errors: list[SourceError] = []

        for source in self.sources:
            if entry is not None:
                missing = set(entry.missing_fields())
                if not missing:
                    break
                if not missing & source.provides:
                    continue
            if self._cooling_down.get(source, 0) > time.monotonic():
                errors.append(SourceError(f"{source.name}: skipped after a recent failure"))
                continue
            try:
                result = source.lookup(word)
            except Exception as exc:
                if isinstance(exc, SourceError):
                    log.warning("%s", exc)
                else:
                    # A parsing bug or odd response in one source shouldn't take down the rest.
                    log.warning("%s: unexpected error", source.name, exc_info=True)
                    exc = SourceError(f"{source.name}: unexpected {type(exc).__name__}")
                errors.append(exc)
                self._cooling_down[source] = time.monotonic() + self.source_cooldown.total_seconds()
                continue

            if result is None:
                log.debug("%s: no entry for %r", source.name, word)
            elif entry is not None:
                entry = entry.fill_missing_from(result)
            elif result.senses:
                entry = result
                for extra in early_extras:
                    entry = entry.fill_missing_from(extra)
            else:
                early_extras.append(result)

        if entry is None:
            if errors:
                raise LookupFailedError(word, errors)
            raise WordNotFoundError(word)
        return entry, errors

    # --- Lifecycle ---

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> WordOfTheDay:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
