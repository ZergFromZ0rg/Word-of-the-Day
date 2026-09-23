"""Command-line interface: `word-of-the-day` or `python -m word_of_day`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from .errors import LookupFailedError, WordNotFoundError, WordOfTheDayError
from .formatting import format_entry
from .service import WordOfTheDay


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_dotenv(find_dotenv(usecwd=True))
    _configure_logging(args.verbose)

    words_file = args.words or Path(os.environ.get("WOTD_WORDS_FILE", "words.txt"))
    cache_dir = None if args.no_cache else (
        args.cache_dir or Path(os.environ.get("WOTD_CACHE_DIR", "cache"))
    )

    with WordOfTheDay.from_env(words_file, cache_dir) as wotd:
        try:
            if args.check:
                return _check(wotd, refresh=args.refresh)
            if args.word:
                day = None
                entry = wotd.lookup(args.word, refresh=args.refresh)
            else:
                day = args.date or date.today()
                entry = wotd.for_date(day, refresh=args.refresh)
        except OSError as exc:
            print(f"error: can't read the word list: {exc}", file=sys.stderr)
            return 1
        except WordOfTheDayError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.json:
        data = {"date": day.isoformat()} if day else {}
        print(json.dumps({**data, **entry.to_dict()}, ensure_ascii=False, indent=2))
    else:
        print(format_entry(entry, day=day))
    return 0


def _check(wotd: WordOfTheDay, *, refresh: bool) -> int:
    """Look up every word in the list (which also fills the cache) and report problems."""
    words = wotd.words()
    problems = 0
    for word in words:
        try:
            entry = wotd.lookup(word, refresh=refresh)
        except WordNotFoundError:
            problems += 1
            print(f"✗ {word}: no dictionary has it")
        except LookupFailedError as exc:
            problems += 1
            print(f"? {word}: {exc}")
        else:
            print(f"✓ {word}  ({', '.join(entry.sources)})")
    print(f"\n{len(words) - problems}/{len(words)} words found")
    return 1 if problems else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="word-of-the-day",
        description="Show the word of the day, looked up in Merriam-Webster and other dictionaries.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--date", type=date.fromisoformat, metavar="YYYY-MM-DD",
                      help="show the word for another day")
    mode.add_argument("--word", help="look up a specific word instead of the day's pick")
    mode.add_argument("--check", action="store_true",
                      help="look up every word in the list and report any that can't be found")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--words", type=Path, metavar="FILE",
                        help="word list (default: $WOTD_WORDS_FILE or words.txt)")
    parser.add_argument("--cache-dir", type=Path, metavar="DIR",
                        help="where lookups are cached (default: $WOTD_CACHE_DIR or cache)")
    parser.add_argument("--no-cache", action="store_true", help="don't read or write the cache")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore cached results and look words up again")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logging")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs, which include the Merriam-Webster API key.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
