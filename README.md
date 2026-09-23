# Word of the Day

[![CI](https://github.com/ZergFromZ0rg/Word-of-the-Day/actions/workflows/ci.yml/badge.svg)](https://github.com/ZergFromZ0rg/Word-of-the-Day/actions/workflows/ci.yml)

Picks a word from `words.txt` each day and looks it up in Merriam-Webster and other
dictionaries, returning clean, structured data (definitions, examples, synonyms,
pronunciation, etymology) that's ready for a homepage widget or an API.

```
$ word-of-the-day
WORD OF THE DAY · Wednesday, September 23, 2026
===============================================

perspicacious

adjective
  1. Of acute discernment; having keen insight; mentally perceptive.
  2. Able to physically see clearly; quick-sighted; sharp-sighted.

Synonyms: sagacious, discerning, sapient, wise, clear-sighted, clear-eyed

Source: Wiktionary, Datamuse
https://en.wiktionary.org/wiki/perspicacious
```

(That run had no API keys. With Merriam-Webster keys you also get pronunciation, audio,
etymology, first known use, and M-W's own definitions and examples.)

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

It works without any API keys, using the free sources. For Merriam-Webster, register at
[dictionaryapi.com](https://dictionaryapi.com/register/index) and request these two APIs:

- **Collegiate Dictionary** → `MW_DICTIONARY_KEY` (definitions, examples, pronunciation,
  audio, etymology)
- **Collegiate Thesaurus** → `MW_THESAURUS_KEY` (synonyms, antonyms). Optional: without
  it, synonyms come from the dictionary's synonym discussions where a word has one, and
  from Datamuse otherwise.

Put the keys in `.env`, which is git-ignored. The free tier is for non-commercial use,
up to 1,000 requests per day per key.

Set `WOTD_TIMEZONE` (e.g. `America/Toronto`) to control when "today" starts. Otherwise
the machine's own time zone is used, which is usually UTC inside Docker.

## Command line

```bash
word-of-the-day                      # today's word
word-of-the-day --date 2026-12-25    # the word for another day (future days are a preview)
word-of-the-day --word laconic       # look up any word
word-of-the-day --json               # JSON output
word-of-the-day --quiz               # test yourself on a word from the past week
word-of-the-day --import-mw-wotd     # add Merriam-Webster's recent Words of the Day to words.txt
word-of-the-day --check              # verify every word in words.txt can be found
word-of-the-day --refresh            # ignore the cache
word-of-the-day --help
```

`python -m word_of_day` works the same way.

## As a library

```python
from word_of_day import WordOfTheDay

with WordOfTheDay.from_env("words.txt") as wotd:
    entry = wotd.today()
    past = wotd.recent(7)  # [(date, word), ...] most recent first, e.g. for a quiz

entry.word  # "perspicacious"
entry.definition  # the first definition
entry.senses  # [Sense(definition, part_of_speech, examples), ...]
entry.synonyms  # ["sagacious", ...]
entry.pronunciation  # "\i-ˈfem-rəl\" style from M-W
entry.audio_url  # MP3 link, if available
entry.etymology  # "Greek ephēmeros lasting a day, ..."
entry.first_known_use  # "1576"
entry.sources  # ["Merriam-Webster"]
entry.to_dict()  # JSON-ready dict
```

`from_env` reads settings from environment variables and uses `cache/` and
`history.json` by default (pass `None` to turn either off). It doesn't load `.env`
itself; your app decides how configuration gets in.

## HTTP API

For the homepage. Install the optional API dependencies, then start the server:

```bash
pip install -e ".[api]"
word-of-the-day-api                  # http://127.0.0.1:8000, interactive docs at /docs
```

| Endpoint | Returns |
| --- | --- |
| `GET /word-of-the-day` | `{"date": "2026-09-23", "entry": {...}}` for today |
| `GET /word-of-the-day/{YYYY-MM-DD}` | the same for another date (future dates are a preview) |
| `GET /words/{word}` | the entry for any word |
| `GET /recent?days=7` | `[{"date": ..., "word": ...}]` for earlier days, most recent first |
| `GET /health` | `{"status": "ok", "version": ..., "today": ..., "words": 30}` |

`entry` has the same fields as `WordEntry` above. Errors come back as
`{"detail": "..."}` with 404 (no dictionary has the word), 502 (dictionaries
unreachable) or 500 (configuration problem, such as a missing word list).

It uses the same settings as the command line, plus `WOTD_HOST` (default `127.0.0.1`;
use `0.0.0.0` to accept other machines), `WOTD_PORT` (default `8000`) and
`WOTD_CORS_ORIGINS` (default `*`, which lets any web page call it). From the homepage:

```js
const res = await fetch("http://homelab.local:8000/word-of-the-day");
const { date, entry } = await res.json();
// entry.word, entry.pronunciation, entry.senses[0].definition, entry.audio_url ...
```

For more uvicorn options (workers, TLS, reload), run it directly:
`uvicorn --factory word_of_day.api:app_from_env --host 0.0.0.0`.

## How it works

```
words.txt + history.json ──► choose today's word ──► cache hit? ──yes──► WordEntry
                                                          │
                                                          no
                                                          ▼
                             sources, in priority order, until nothing is missing
                             ├─ Merriam-Webster  (needs keys)
                             ├─ Wiktionary       (definitions only)
                             └─ Datamuse         (synonyms/antonyms only)
                                                          │
                                                          ▼
                                              normalized WordEntry ──► cache
```

**Choosing a word.** Today's pick is recorded in `history.json`, so it stays the same
all day even if you edit `words.txt`. The only exception is removing today's word from
the list, which picks a new one. New days get a word you haven't had yet, at random.
Once every word has been used, the pick comes at random from the half of the list you
saw longest ago. Words just added to the list therefore come up soon, and nothing
repeats two days in a row. Picks are deterministic, so separate processes agree.

**Unknown words.** If no dictionary has the chosen word, it's recorded under
`not_found` in the history and never picked again, and another word is chosen instead.
`--check` lists these so you can fix or remove them.

**Combining sources.** Definitions all come from the first source that has any, because
senses from different dictionaries don't line up. If that entry is missing synonyms,
antonyms or pronunciation, later sources are asked for just those gaps. A source that
can't supply any of them is skipped.

**Failures.** A source that errors (timeout, bad key, rate limit, 5xx) is skipped and
the next one is tried. If no source has the word you get `WordNotFoundError`. If
sources failed and none found it you get `LookupFailedError`, since the word may exist.
Both inherit from `WordOfTheDayError`.

**Cache.** One JSON file per word in `cache/`, kept for 30 days. Entries built while a
source was failing expire after one day, so they get another chance. To avoid a slow
first page load each day, prefetch with cron. Importing from the feed at the same time
keeps the list growing:

```
5 0 * * * cd /path/to/Word-of-the-Day && .venv/bin/word-of-the-day --import-mw-wotd && .venv/bin/word-of-the-day > /dev/null
```

## Merriam-Webster API quirks

- An unknown word returns HTTP 200 with a list of spelling suggestions, not a 404.
- A bad key returns HTTP 200 with a plain-text error, not JSON.
- Definitions contain formatting tokens (`{bc}`, `{it}…{/it}`, `{sx|word||}`) that
  `clean_markup()` strips.
- Results include entries for related words, so they're filtered by headword. An
  inflected form without its own entry, like "ephemerals", resolves to "ephemeral".

## Project layout

```
src/word_of_day/
├── models.py          WordEntry and Sense dataclasses
├── selector.py        reading/appending words.txt, choosing a word
├── history.py         which day got which word (history.json)
├── service.py         WordOfTheDay: choosing + sources + cache
├── cache.py           JSON file cache
├── feed.py            Merriam-Webster Word of the Day RSS import
├── formatting.py      terminal output
├── cli.py             command-line interface
├── api.py             HTTP API (FastAPI)
└── sources/
    ├── base.py            DictionarySource interface, HTTP error handling
    ├── merriam_webster.py
    ├── wiktionary.py
    └── datamuse.py
tests/                 offline tests (HTTP is mocked)
.github/workflows/     CI: lint, format, type-check, tests on Python 3.10–3.14
```

To add a dictionary, subclass `DictionarySource`, implement
`lookup(word) -> WordEntry | None`, and add it to `default_sources()`.

## Development

```bash
pytest               # tests
ruff check .         # lint
ruff format .        # format
mypy                 # type-check
```

CI runs all four on every pull request and on pushes to `main`.

## Attribution

Wiktionary content is CC BY-SA, so show the source name and link (`entry.sources`,
`entry.source_url`) wherever you display it. Merriam-Webster's terms also require
attribution.

## Next steps

- Docker image for the homelab (mount `cache/` and `history.json`, set `WOTD_TIMEZONE`)
- The homepage widget: word, definition, pronunciation button, quiz card
- SQLite in place of the JSON files
