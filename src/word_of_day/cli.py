"""Command-line interface: `word-of-the-day` or `python -m word_of_day`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from datetime import date
from pathlib import Path

import httpx
from dotenv import find_dotenv, load_dotenv

from .errors import LookupFailedError, WordNotFoundError, WordOfTheDayError
from .feed import fetch_feed_words
from .formatting import format_entry
from .selector import add_words
from .service import HTTP_TIMEOUT, USER_AGENT, WordOfTheDay


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_dotenv(find_dotenv(usecwd=True))
    _configure_logging(args.verbose)

    words_file = args.words or Path(os.environ.get("WOTD_WORDS_FILE", "words.txt"))
    history_file = args.history_file or Path(os.environ.get("WOTD_HISTORY_FILE", "history.json"))
    cache_dir = (
        None if args.no_cache else args.cache_dir or Path(os.environ.get("WOTD_CACHE_DIR", "cache"))
    )

    try:
        if args.import_mw_wotd:
            return _import_mw_wotd(words_file)
        with WordOfTheDay.from_env(words_file, cache_dir, history_file) as wotd:
            if args.check:
                return _check(wotd, refresh=args.refresh)
            if args.quiz:
                return _quiz(wotd)
            if args.word:
                day = None
                entry = wotd.lookup(args.word, refresh=args.refresh)
            else:
                day = args.date or wotd.current_date()
                entry = wotd.for_date(day, refresh=args.refresh)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
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


def _quiz(wotd: WordOfTheDay) -> int:
    """Show one of the past week's words and reveal its meaning on Enter."""
    recent = wotd.recent(7)
    if not recent:
        print("No earlier words yet. Come back tomorrow!")
        return 0
    day, word = random.choice(recent)
    print(f"On {day:%A, %B} {day.day} the word was: {word}")
    if sys.stdin.isatty():
        input("Remember what it means? Press Enter to check. ")
    print()
    print(format_entry(wotd.lookup(word)))
    return 0


def _import_mw_wotd(words_file: Path) -> int:
    with httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        feed_words = fetch_feed_words(client)
    added = add_words(words_file, feed_words)
    if added:
        print(f"Added {len(added)} word(s) to {words_file}: {', '.join(added)}")
    else:
        print(f"Nothing new: {words_file} already has all {len(feed_words)} words from the feed.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="word-of-the-day",
        description="Show the word of the day, from Merriam-Webster and other dictionaries.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--date",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="show the word for another day (future days are a preview)",
    )
    mode.add_argument("--word", help="look up a specific word instead of the day's pick")
    mode.add_argument(
        "--check",
        action="store_true",
        help="look up every word in the list and report any that can't be found",
    )
    mode.add_argument(
        "--quiz", action="store_true", help="test yourself on a word from the past week"
    )
    mode.add_argument(
        "--import-mw-wotd",
        action="store_true",
        help="add recent Merriam-Webster Words of the Day to the word list",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument(
        "--words",
        type=Path,
        metavar="FILE",
        help="word list (default: $WOTD_WORDS_FILE or words.txt)",
    )
    parser.add_argument(
        "--history-file",
        type=Path,
        metavar="FILE",
        help="record of past days' words (default: $WOTD_HISTORY_FILE or history.json)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        metavar="DIR",
        help="where lookups are cached (default: $WOTD_CACHE_DIR or cache)",
    )
    parser.add_argument("--no-cache", action="store_true", help="don't read or write the cache")
    parser.add_argument(
        "--refresh", action="store_true", help="ignore cached results and look words up again"
    )
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
