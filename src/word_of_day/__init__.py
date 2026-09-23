"""Pick a daily word from a list and look it up in Merriam-Webster and other dictionaries.

    from word_of_day import WordOfTheDay

    with WordOfTheDay.from_env("words.txt") as wotd:
        entry = wotd.today()
        print(entry.word, entry.definition)
"""

__version__ = "0.1.0"

from .cache import JsonFileCache
from .errors import LookupFailedError, SourceError, WordNotFoundError, WordOfTheDayError
from .formatting import format_entry
from .models import Sense, WordEntry
from .selector import load_words, pick_word
from .service import WordOfTheDay
from .sources import (
    DatamuseSource,
    DictionarySource,
    FreeDictionarySource,
    MerriamWebsterSource,
    WiktionarySource,
    default_sources,
)

__all__ = [
    "DatamuseSource",
    "DictionarySource",
    "FreeDictionarySource",
    "JsonFileCache",
    "LookupFailedError",
    "MerriamWebsterSource",
    "Sense",
    "SourceError",
    "WiktionarySource",
    "WordEntry",
    "WordNotFoundError",
    "WordOfTheDay",
    "WordOfTheDayError",
    "default_sources",
    "format_entry",
    "load_words",
    "pick_word",
]
