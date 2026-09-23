# Word of the Day

Picks a word from `words.txt` each day and looks it up in Merriam-Webster and other
dictionaries, returning clean, structured data (definitions, examples, synonyms,
pronunciation) that's ready for a homepage widget or an API.

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
and M-W's definitions and examples.)

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

- **Collegiate Dictionary** → `MW_DICTIONARY_KEY` (definitions, examples, pronunciation, audio)
- **Collegiate Thesaurus** → `MW_THESAURUS_KEY` (synonyms, antonyms)

Put the keys in `.env`, which is git-ignored. The free tier is for non-commercial use,
up to 1,000 requests per day per key.

## Command line

```bash
word-of-the-day                      # today's word
word-of-the-day --date 2026-12-25    # the word for another day
word-of-the-day --word laconic       # look up any word
word-of-the-day --json               # JSON output
word-of-the-day --check              # verify every word in words.txt can be found
word-of-the-day --refresh            # ignore the cache
word-of-the-day --help
```

`python -m word_of_day` works the same way.

## As a library

```python
from word_of_day import WordOfTheDay

with WordOfTheDay.from_env("words.txt", cache_dir="cache") as wotd:
    entry = wotd.today()

entry.word              # "perspicacious"
entry.definition        # first definition
entry.senses            # [Sense(definition, part_of_speech, examples), ...]
entry.synonyms          # ["sagacious", ...]
entry.pronunciation     # e.g. "\i-ˈfem-rəl\" (M-W) or "/ɪˈfɛm(ə)ɹəl/" (IPA)
entry.audio_url         # MP3 link, if available
entry.sources           # ["Merriam-Webster"]
entry.to_dict()         # JSON-ready dict
```

`from_env` reads the API keys from environment variables. It doesn't load `.env` itself;
your app decides how configuration gets in. A FastAPI endpoint, for example:

```python
from fastapi import FastAPI, HTTPException
from word_of_day import WordOfTheDay, WordOfTheDayError

app = FastAPI()
wotd = WordOfTheDay.from_env("words.txt", cache_dir="cache")

@app.get("/word-of-the-day")
def word_of_the_day():  # sync endpoint: FastAPI runs it in a thread pool
    try:
        return wotd.today().to_dict()
    except WordOfTheDayError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
```

## How it works

```
words.txt ──► selector ──► today's word ──► cache hit? ──yes──► WordEntry
                                                │
                                                no
                                                ▼
                     sources, in priority order, until nothing is missing
                     ├─ Merriam-Webster     (needs keys)
                     ├─ Free Dictionary API (dictionaryapi.dev)
                     ├─ Wiktionary          (definitions only)
                     └─ Datamuse            (synonyms/antonyms only)
                                                │
                                                ▼
                                    normalized WordEntry ──► cache
```

**Selection.** Deterministic, with no stored state: the same list and date always give
the same word. Each run of *N* days (for *N* words) is a fresh shuffle, so every word
comes up once per cycle and never two days in a row. The order of lines in the file
doesn't matter, but adding or removing words reshuffles future days. "Today" is based on
the machine's local time zone, so set `TZ` in Docker.

**Combining sources.** Definitions all come from the first source that has any, because
senses from different dictionaries don't line up. If that entry is missing synonyms,
antonyms or pronunciation, later sources are asked only for those gaps. A source that
can't provide a missing field is skipped.

**Failures.** A source that errors (timeout, bad key, rate limit, 5xx) is skipped for five
minutes, and the next one is tried. If no source has the word you get `WordNotFoundError`.
If sources failed and none found it you get `LookupFailedError`, since the word may exist.
Both inherit from `WordOfTheDayError`.

**Cache.** One JSON file per word in `cache/`, kept for 30 days. Entries built while a
source was failing expire after one day, so they get another chance. To avoid a slow
first page load each day, prefetch with cron: `5 0 * * * cd /path && .venv/bin/word-of-the-day > /dev/null`.

## Merriam-Webster API quirks

- An unknown word returns HTTP 200 with a list of spelling suggestions, not a 404.
- A bad key returns HTTP 200 with a plain-text error, not JSON.
- Definitions contain formatting tokens (`{bc}`, `{it}…{/it}`, `{sx|word||}`) that
  `clean_markup()` strips.
- Results include entries for related words, so they're filtered by headword. An
  inflected form like "ran" resolves to "run".

## Project layout

```
src/word_of_day/
├── models.py          WordEntry and Sense dataclasses
├── selector.py        reading words.txt, picking the day's word
├── service.py         WordOfTheDay: selection + sources + cache
├── cache.py           JSON file cache
├── formatting.py      terminal output
├── cli.py             command-line interface
└── sources/
    ├── base.py            DictionarySource interface, HTTP error handling
    ├── merriam_webster.py
    ├── free_dictionary.py
    ├── wiktionary.py
    └── datamuse.py
tests/                 offline tests (HTTP is mocked)
```

To add a dictionary, subclass `DictionarySource`, implement
`lookup(word) -> WordEntry | None`, and add it to `default_sources()`.

## Tests

```bash
pytest
```

## Attribution

Wiktionary and Free Dictionary API content is CC BY-SA, so show the source name and link
(`entry.sources`, `entry.source_url`) wherever you display it. Merriam-Webster's terms
also require attribution.

## Next steps

- FastAPI service wrapping the library (see the example above)
- SQLite in place of the JSON cache
- Docker image for the homelab
