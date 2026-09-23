"""WordOfTheDay: ties the word list, history, dictionary sources and cache together."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from . import __version__
from .cache import JsonFileCache
from .errors import LookupFailedError, SourceError, WordNotFoundError, WordOfTheDayError
from .history import History
from .models import WordEntry
from .selector import DEFAULT_SEED, choose_word, load_words
from .sources import DictionarySource, default_sources

USER_AGENT = f"word-of-the-day/{__version__} (+https://github.com/ZergFromZ0rg/Word-of-the-Day)"
# Short enough that a dictionary that's down doesn't stall a page load for long.
HTTP_TIMEOUT = 8.0
# Entries assembled while a source was failing are re-fetched sooner than usual.
DEGRADED_CACHE_AGE = timedelta(days=1)
# How many unfindable words to skip in a row before giving up on a day.
MAX_PICKS = 5

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
        history_file: str | Path | None = None,
        timezone: str | tzinfo | None = None,
        seed: str = DEFAULT_SEED,
        client: httpx.Client | None = None,
    ):
        """Wire things up explicitly.

        Without a `history_file`, picks are only remembered while this object lives.
        `timezone` is a name like "America/Toronto"; None means the machine's zone.
        `client`, if given, is closed by close().
        """
        self.words_file = Path(words_file)
        self.sources = list(sources)
        self.cache = cache
        self.history_file = Path(history_file) if history_file is not None else None
        self.timezone = _timezone(timezone)
        self.seed = seed
        self._client = client
        self._memory_history = History()
        self._lock = threading.Lock()

    @classmethod
    def from_env(
        cls,
        words_file: str | Path = "words.txt",
        cache_dir: str | Path | None = "cache",
        history_file: str | Path | None = "history.json",
        *,
        env: Mapping[str, str] | None = None,
        seed: str = DEFAULT_SEED,
    ) -> WordOfTheDay:
        """Build with the default sources and settings from environment variables.

        Reads MW_DICTIONARY_KEY, MW_THESAURUS_KEY and WOTD_TIMEZONE. Pass None for
        cache_dir or history_file to turn those off. This doesn't read .env files;
        the CLI does that itself.
        """
        env = os.environ if env is None else env
        timezone = _timezone(env.get("WOTD_TIMEZONE") or None)
        client = httpx.Client(
            timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        sources = default_sources(
            client,
            mw_dictionary_key=env.get("MW_DICTIONARY_KEY"),
            mw_thesaurus_key=env.get("MW_THESAURUS_KEY"),
        )
        cache = JsonFileCache(cache_dir) if cache_dir is not None else None
        return cls(
            words_file,
            sources,
            cache,
            history_file=history_file,
            timezone=timezone,
            seed=seed,
            client=client,
        )

    # --- Choosing (no network) ---

    def current_date(self) -> date:
        """Today in the configured time zone."""
        return datetime.now(self.timezone).date()

    def words(self) -> list[str]:
        """The word list, re-read on every call so edits apply without a restart."""
        words = load_words(self.words_file)
        if not words:
            raise WordOfTheDayError(f"{self.words_file} doesn't contain any words")
        return words

    def word_for(self, day: date | None = None) -> str:
        """The word for `day` (default: today), without looking it up.

        Days in the history return their recorded word. Other days return a preview:
        only today()/for_date() on the current date records a pick, so the word
        previewed for a future date can still change.
        """
        day = day or self.current_date()
        return self._pick(self.words(), self._load_history(), day)

    def recent(self, count: int = 7) -> list[tuple[date, str]]:
        """Words recorded for days before today, most recent first (e.g. for a quiz)."""
        return self._load_history().before(self.current_date())[:count]

    # --- Lookup ---

    def today(self, *, refresh: bool = False) -> WordEntry:
        return self.for_date(self.current_date(), refresh=refresh)

    def for_date(self, day: date, *, refresh: bool = False) -> WordEntry:
        """Look up the word for `day`. For the current date, the pick is recorded.

        A word no dictionary knows is remembered as not found and another is picked.
        """
        with self._lock:
            history = self._load_history()
            words = self.words()
            skipped: list[str] = []
            changed = False
            try:
                for _ in range(MAX_PICKS):
                    word = self._pick(words, history, day, exclude=skipped)
                    try:
                        entry = self.lookup(word, refresh=refresh)
                    except WordNotFoundError:
                        log.warning(
                            "no dictionary has %r, so it will be skipped (remove it from %s)",
                            word,
                            self.words_file,
                        )
                        skipped.append(word)
                        history.not_found.add(word.casefold())
                        changed = True
                        continue

                    if day == self.current_date() and history.days.get(day) != word:
                        history.days[day] = word
                        changed = True
                    return entry
                raise WordOfTheDayError(f"no dictionary has any of: {', '.join(skipped)}")
            finally:
                # Also runs when giving up, so known-bad words aren't tried again.
                if changed:
                    self._save_history(history)

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
        errors: list[SourceError] = []

        for source in self.sources:
            if entry is not None:
                missing = set(entry.missing_fields())
                if not missing:
                    break
                if not missing & source.provides:
                    continue
            try:
                result = source.lookup(word)
            except SourceError as exc:
                log.warning("%s", exc)
                errors.append(exc)
                continue
            except Exception as exc:
                # A parsing bug or odd response in one source shouldn't take down the rest.
                log.warning("%s: unexpected error", source.name, exc_info=True)
                errors.append(SourceError(f"{source.name}: unexpected {type(exc).__name__}"))
                continue

            if result is None:
                log.debug("%s: no entry for %r", source.name, word)
            elif entry is not None:
                entry = entry.fill_missing_from(result)
            elif result.senses:
                entry = result
            # A result without senses before any definitions (a thesaurus listed first)
            # is ignored: list sources that supply definitions first.

        if entry is None:
            if errors:
                raise LookupFailedError(word, errors)
            raise WordNotFoundError(word)
        return entry, errors

    # --- History ---

    def _pick(
        self, words: list[str], history: History, day: date, exclude: Collection[str] = ()
    ) -> str:
        recorded = history.days.get(day)
        still_listed = {w.casefold() for w in words} - {w.casefold() for w in exclude}
        # A recorded word stands unless it has since been removed from the list.
        if recorded and recorded.casefold() in still_listed:
            return recorded
        try:
            return choose_word(
                words, history.days, day, seed=self.seed, exclude={*history.not_found, *exclude}
            )
        except ValueError:
            raise WordOfTheDayError(
                f"no usable words left in {self.words_file}: every word is marked as not found"
            ) from None

    def _load_history(self) -> History:
        if self.history_file is None:
            return self._memory_history
        return History.load(self.history_file)

    def _save_history(self, history: History) -> None:
        if self.history_file is None:
            self._memory_history = history
        else:
            history.save(self.history_file)

    # --- Lifecycle ---

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> WordOfTheDay:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _timezone(value: str | tzinfo | None) -> tzinfo | None:
    if value is None or isinstance(value, tzinfo):
        return value
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise WordOfTheDayError(f"unknown time zone {value!r}") from exc
