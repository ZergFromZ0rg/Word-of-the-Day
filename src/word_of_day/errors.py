from __future__ import annotations


class WordOfTheDayError(Exception):
    """Base class for everything this package raises on purpose."""


class SourceError(WordOfTheDayError):
    """A dictionary source couldn't answer: network error, bad API key, rate limit, etc.

    Messages never contain request URLs, because those can include API keys.
    """


class WordNotFoundError(WordOfTheDayError):
    """Every source answered, and none of them knows the word."""

    def __init__(self, word: str):
        super().__init__(f"no dictionary has an entry for {word!r}")
        self.word = word


class LookupFailedError(WordOfTheDayError):
    """No source found the word, and at least one failed, so the word may still exist."""

    def __init__(self, word: str, errors: list[SourceError]):
        details = "; ".join(str(error) for error in errors)
        super().__init__(f"couldn't look up {word!r}: {details}")
        self.word = word
        self.errors = errors
