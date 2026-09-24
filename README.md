# Word of the Day

[![CI](https://github.com/ZergFromZ0rg/Word-of-the-Day/actions/workflows/ci.yml/badge.svg)](https://github.com/ZergFromZ0rg/Word-of-the-Day/actions/workflows/ci.yml)

Picks a word from a text file each day and looks it up in Merriam-Webster and other
dictionaries: definitions, examples, synonyms, pronunciation and word origin.
Use it from the terminal, from Python, or over HTTP for a dashboard.

```
$ word-of-the-day
WORD OF THE DAY · Wednesday, September 23, 2026
===============================================

recalcitrant  \ri-ˈkal-sə-trənt\

adjective
  1. obstinately defiant of authority or restraint

Origin: Late Latin recalcitrant-, from Latin recalcitrare to kick back
First known use: 1797

Synonyms: defiant, intractable, refractory
Source: Merriam-Webster
```

## Quick start

Needs Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
word-of-the-day
```

It works with no setup. Add your own words, one per line, to `words.txt`.

**Optional:** for Merriam-Webster's own definitions, pronunciation and origin, get a free
key at [dictionaryapi.com](https://dictionaryapi.com/register/index) (choose "Collegiate
Dictionary"). Then `cp .env.example .env` and paste it after `MW_DICTIONARY_KEY=`.

## Commands

```bash
word-of-the-day                    # today's word
word-of-the-day --word laconic     # look up any word
word-of-the-day --date 2026-12-25  # another day
word-of-the-day --quiz             # quiz yourself on a recent word
word-of-the-day --import-mw-wotd   # add Merriam-Webster's recent words to your list
word-of-the-day --check            # make sure every word in your list can be found
word-of-the-day --json             # JSON output
```

Today's word is saved in `history.json`, so it stays the same all day even if you
edit the list.

## Use it in Python

```python
from word_of_day import WordOfTheDay

with WordOfTheDay.from_env("words.txt") as wotd:
    entry = wotd.today()

print(entry.word, entry.definition, entry.synonyms)
```

## Use it over HTTP

```bash
pip install -e ".[api]"
word-of-the-day-api        # http://127.0.0.1:8000, docs at /docs
```

`GET /word-of-the-day` returns today's word as JSON. `GET /widget` returns it as flat
fields for dashboards.

## Where the word comes from

By default the word comes from your list, and each word is used once before any repeats.
To use **Merriam-Webster's own Word of the Day** instead, set `WOTD_WORD_SOURCE=merriam`
in `.env` (or run with `--source merriam`). If their feed is down or hasn't posted yet,
your list is the fallback until it does. A word shown from your list stays for the rest
of the day, so switching sources takes effect tomorrow.

`word-of-the-day --history` lists every word shown so far, and `/manage` shows the same
list in a browser.

## Use your own word list

- **Terminal:** put words in any text file (one per line) and run
  `word-of-the-day --words mywords.txt`, or just edit `words.txt`.
- **Over HTTP:** set `WOTD_ADMIN_TOKEN` to a long random secret, then upload a file:
  ```bash
  curl -X PUT -H "Authorization: Bearer $WOTD_ADMIN_TOKEN" \
       --data-binary @mywords.txt http://localhost:8000/word-list
  ```
  This replaces the list. Add `?mode=add` to append instead. Uploads are disabled
  unless the token is set.
- **In a browser:** open `http://localhost:8000/manage` to see today's word, the words
  shown before, and the list. Upload a file, or click **Edit current list**, change it,
  and click **Replace list** (you type the token each time; it's never stored).

## Homepage dashboard (optional)

Files in [`integrations/homepage/`](integrations/homepage) run the API in Docker and add
a widget to [Homepage](https://gethomepage.dev):

```bash
docker compose -f integrations/homepage/docker-compose.yml up -d --build
```

Then paste `services.yaml` from that folder into your Homepage config.

## More

- [Advanced guide](docs/advanced.md): how words are chosen, settings, every API endpoint, project layout
- Development: `pip install -e ".[dev]"`, then `pytest`, `ruff check .`, `mypy`

Definitions from Wiktionary are CC BY-SA, so show the source name and link when you
display them.
