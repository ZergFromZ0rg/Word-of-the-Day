"""Merriam-Webster's Collegiate Dictionary and Collegiate Thesaurus.

API keys: https://dictionaryapi.com/register/index (free for non-commercial use,
1,000 requests/day per key). Response format: https://dictionaryapi.com/products/json

Quirks handled here:
- An unknown word returns HTTP 200 with a list of spelling suggestions (strings)
  in place of entry objects, not a 404.
- A bad key returns HTTP 200 with a plain-text error, not JSON.
- A lookup also returns entries for related words and phrases ("ephemeral pond"),
  so entries are filtered by headword.
- Definition text is full of formatting tokens like {bc}, {it}...{/it}, {sx|word||}.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any

import httpx

from ..errors import SourceError
from ..models import FILLABLE_FIELDS, Sense, WordEntry, unique
from .base import MAX_RELATED_WORDS, DictionarySource, url_path_word

DICTIONARY_URL = "https://www.dictionaryapi.com/api/v3/references/collegiate/json/{word}"
THESAURUS_URL = "https://www.dictionaryapi.com/api/v3/references/thesaurus/json/{word}"
AUDIO_URL = "https://media.merriam-webster.com/audio/prons/en/us/mp3/{folder}/{name}.mp3"
PAGE_URL = "https://www.merriam-webster.com/dictionary/{word}"

log = logging.getLogger(__name__)


class MerriamWebsterSource(DictionarySource):
    name = "Merriam-Webster"

    def __init__(self, client: httpx.Client, dictionary_key: str, thesaurus_key: str | None = None):
        super().__init__(client)
        self.dictionary_key = dictionary_key
        self.thesaurus_key = thesaurus_key
        provides = {"senses", *FILLABLE_FIELDS}
        if not thesaurus_key:
            provides -= {"synonyms", "antonyms"}
        self.provides = frozenset(provides)

    def lookup(self, word: str) -> WordEntry | None:
        data = self._get(DICTIONARY_URL, word, self.dictionary_key)
        entries = matching_entries(data, word)
        if not entries:
            return None
        entry = parse_dictionary(entries)
        entry.sources = [self.name]

        if self.thesaurus_key:
            try:
                data = self._get(THESAURUS_URL, entry.word, self.thesaurus_key)
            except SourceError as exc:
                # The definitions are still good; other sources can supply synonyms.
                log.warning("%s (thesaurus); continuing without synonyms", exc)
            else:
                thesaurus = matching_entries(data, entry.word)
                entry.synonyms, entry.antonyms = parse_thesaurus(thesaurus, entry.word)
        return entry

    def _get(self, url: str, word: str, key: str) -> Any:
        return self.get_json(url.format(word=url_path_word(word)), params={"key": key})


# --- Parsing -----------------------------------------------------------------
# These functions only deal with already-decoded JSON, so they're easy to test.


def headword(entry: dict[str, Any]) -> str:
    """ "ephemeral:2" -> "ephemeral" (the suffix is the homograph number)."""
    return str(entry.get("meta", {}).get("id", "")).split(":")[0]


def matching_entries(data: Any, word: str) -> list[dict[str, Any]]:
    """The entries for `word` itself, or [] if Merriam-Webster doesn't know it."""
    if not isinstance(data, list):
        return []
    # Spelling suggestions come back as bare strings; those mean "not found".
    entries = [item for item in data if isinstance(item, dict)]
    if not entries:
        return []
    exact = [e for e in entries if headword(e).casefold() == word.casefold()]
    if exact:
        return exact
    # A form without its own entry, like "ephemerals", returns entries for the base
    # word ("ephemeral:2"): keep the best match.
    best = headword(entries[0])
    return [e for e in entries if headword(e) == best]


def parse_dictionary(entries: list[dict[str, Any]]) -> WordEntry:
    word = headword(entries[0])
    senses: list[Sense] = []
    for entry in entries:
        part_of_speech = entry.get("fl")
        entry_senses = list(_senses(entry, part_of_speech))
        if not entry_senses:
            # Fall back to the pre-cleaned short definitions, then to cross-references
            # ("less common spelling of bologna").
            texts = entry.get("shortdef") or [_cross_reference(entry)]
            entry_senses = [
                Sense(clean_markup(t), part_of_speech) for t in texts if clean_markup(t)
            ]
        senses.extend(entry_senses)

    pronunciation, audio_url = _pronunciation(entries)
    # Homographs have separate histories; use the first (main) entry that has one.
    etymology = next(filter(None, map(_etymology, entries)), None)
    first_known_use = next(filter(None, (clean_markup(e.get("date", "")) for e in entries)), None)
    return WordEntry(
        word=word,
        senses=senses,
        pronunciation=pronunciation,
        audio_url=audio_url,
        etymology=etymology,
        first_known_use=first_known_use,
        source_url=PAGE_URL.format(word=url_path_word(word)),
    )


def parse_thesaurus(entries: list[dict[str, Any]], word: str) -> tuple[list[str], list[str]]:
    """Synonyms and antonyms, from the flat per-sense lists in each entry's metadata."""
    synonyms = [s for e in entries for group in e.get("meta", {}).get("syns", []) for s in group]
    antonyms = [a for e in entries for group in e.get("meta", {}).get("ants", []) for a in group]
    return (
        unique(synonyms, exclude=[word], limit=MAX_RELATED_WORDS),
        unique(antonyms, exclude=[word], limit=MAX_RELATED_WORDS),
    )


def _senses(entry: dict[str, Any], part_of_speech: str | None) -> Iterator[Sense]:
    # def -> sseq (numbered groups) -> items like ["sense", {...}], ["bs", ...], ["pseq", [...]]
    for section in entry.get("def", []):
        for group in section.get("sseq", []):
            for sense in _walk(group):
                definition, examples = _parse_sense(sense)
                if definition:
                    yield Sense(definition, part_of_speech, examples)


def _walk(items: list[Any]) -> Iterator[dict[str, Any]]:
    for item in items:
        if not (isinstance(item, list) and len(item) == 2):
            continue
        kind, body = item
        if kind == "sense":
            yield body
        elif kind == "bs":  # "binding substitute": a general sense introducing the next ones
            yield body.get("sense", {})
        elif kind == "pseq":  # parenthesized sub-sequence: (1), (2)...
            yield from _walk(body)
        # "sen" (truncated sense) carries only labels, no definition.


def _parse_sense(sense: dict[str, Any]) -> tuple[str, list[str]]:
    definition, examples = _parse_defining_text(sense.get("dt", []))
    divided = sense.get("sdsense")  # e.g. "...; specifically a theory that..."
    if isinstance(divided, dict):
        extra, extra_examples = _parse_defining_text(divided.get("dt", []))
        if extra:
            extra = f"{divided.get('sd', '')} {extra}".strip()
            definition = f"{definition}; {extra}" if definition else extra
        examples += extra_examples
    return definition, examples


def _parse_defining_text(dt: list[Any]) -> tuple[str, list[str]]:
    texts: list[str] = []
    notes: list[str] = []
    examples: list[str] = []
    for item in dt:
        if not (isinstance(item, list) and len(item) == 2):
            continue
        kind, body = item
        if kind == "text":
            texts.append(body)
        elif kind == "vis":
            examples.extend(_examples(body))
        elif kind == "uns":  # usage notes, e.g. "used chiefly in the phrase in abeyance"
            for note in body:
                note_text, note_examples = _parse_defining_text(note)
                notes.append(note_text)
                examples.extend(note_examples)
    parts = [clean_markup(" ".join(texts)), *notes]
    return " — ".join(p for p in parts if p), examples


def _examples(illustrations: list[Any]) -> Iterator[str]:
    for illustration in illustrations:
        if not isinstance(illustration, dict):
            continue
        text = clean_markup(illustration.get("t", ""))
        if not text:
            continue
        attribution = _attribution(illustration.get("aq"))
        yield f"{text} — {attribution}" if attribution else text


def _attribution(quote: Any) -> str:
    if not isinstance(quote, dict):
        return ""
    parts = [quote.get("auth"), quote.get("source"), quote.get("aqdate")]
    return ", ".join(clean_markup(p) for p in parts if p)


def _etymology(entry: dict[str, Any]) -> str:
    # "et": [["text", "Greek {it}ephēmeros{/it} ..."], ["et_snote", [...]]]
    texts = [
        item[1] for item in entry.get("et", []) if isinstance(item, list) and item[:1] == ["text"]
    ]
    return clean_markup(" ".join(texts))


def _cross_reference(entry: dict[str, Any]) -> str:
    phrases = []
    for reference in entry.get("cxs", []):
        targets = ", ".join(
            " ".join(filter(None, [t.get("cxl"), t.get("cxt"), t.get("cxn")]))
            for t in reference.get("cxtis", [])
        )
        phrases.append(f"{reference.get('cxl', '')} {targets}".strip())
    return ", ".join(p for p in phrases if p)


def _pronunciation(entries: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    for entry in entries:
        for pron in entry.get("hwi", {}).get("prs", []):
            written = pron.get("mw")
            if written:
                audio = pron.get("sound", {}).get("audio")
                return f"\\{written}\\", audio_url(audio) if audio else None
    return None, None


def audio_url(name: str) -> str:
    """Build the MP3 URL for a pronunciation, following the documented folder rules."""
    if name.startswith("bix"):
        folder = "bix"
    elif name.startswith("gg"):
        folder = "gg"
    elif not name[0].isalpha():
        folder = "number"
    else:
        folder = name[0]
    return AUDIO_URL.format(folder=folder, name=name)


# --- Markup ------------------------------------------------------------------

# Cross-reference groups like {dx}see {dxt|x||}{/dx} are dropped along with their content.
_DROPPED_GROUPS = re.compile(r"\{(dx|dx_def|dx_ety|ma)\}.*?\{/\1\}", re.S)
# Link tokens keep only their display text: {sx|transient||} -> transient.
_LINKS = re.compile(r"\{(?:a_link|d_link|i_link|et_link|mat|sx|dxt)\|([^|}]*)[^}]*\}")
# Anything else ({it}, {/it}, {wi}, {ds||1||}...) is formatting: remove the token, keep the text.
_ANY_TOKEN = re.compile(r"\{[^}]*\}")
_REPLACEMENTS = {"{bc}": "; ", "{ldquo}": "“", "{rdquo}": "”", "{p_br}": " "}


def clean_markup(text: str) -> str:
    """Turn Merriam-Webster running text into plain text."""
    text = _DROPPED_GROUPS.sub("", text)
    for token, replacement in _REPLACEMENTS.items():
        text = text.replace(token, replacement)
    text = _LINKS.sub(r"\1", text)
    text = _ANY_TOKEN.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([;,.:!?)])", r"\1", text)
    text = re.sub(r"(?:;\s*)+", "; ", text)  # {bc} runs: "a ; ; b" -> "a; b"
    return text.strip(" ;")
