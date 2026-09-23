import json
from datetime import date, datetime, timedelta, timezone

import pytest

from word_of_day.cache import JsonFileCache
from word_of_day.errors import LookupFailedError, SourceError, WordNotFoundError, WordOfTheDayError
from word_of_day.models import FILLABLE_FIELDS, Sense, WordEntry
from word_of_day.selector import pick_word
from word_of_day.service import WordOfTheDay
from word_of_day.sources import DictionarySource, MerriamWebsterSource


class FakeSource(DictionarySource):
    """Returns a canned result (or raises a canned exception) and counts calls."""

    def __init__(self, name, result=None, provides=None):
        super().__init__(client=None)
        self.name = name
        self.result = result
        self.calls = 0
        if provides is not None:
            self.provides = frozenset(provides)

    def lookup(self, word):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def entry(source, *, senses=True, **fields):
    return WordEntry(
        word="ephemeral",
        senses=[Sense(f"definition from {source}")] if senses else [],
        sources=[source],
        **fields,
    )


COMPLETE = dict(synonyms=["fleeting"], antonyms=["lasting"], pronunciation="/x/", audio_url="https://a/x.mp3")


@pytest.fixture
def words_file(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("ephemeral\nserendipity\nlaconic\n", encoding="utf-8")
    return path


def make(words_file, *sources, cache=None):
    return WordOfTheDay(words_file, sources, cache)


def test_first_complete_entry_wins_and_later_sources_are_not_called(words_file):
    first = FakeSource("A", entry("A", **COMPLETE))
    second = FakeSource("B", entry("B", **COMPLETE))
    result = make(words_file, first, second).lookup("ephemeral")
    assert result.definition == "definition from A"
    assert second.calls == 0


def test_falls_back_when_a_source_fails(words_file):
    failing = FakeSource("A", SourceError("A: rate limit reached (HTTP 429)"))
    working = FakeSource("B", entry("B", **COMPLETE))
    assert make(words_file, failing, working).lookup("ephemeral").sources == ["B"]


def test_unexpected_exceptions_are_treated_as_source_failures(words_file):
    buggy = FakeSource("A", KeyError("sseq"))
    working = FakeSource("B", entry("B", **COMPLETE))
    assert make(words_file, buggy, working).lookup("ephemeral").sources == ["B"]


def test_gaps_are_filled_from_later_sources(words_file):
    primary = FakeSource("A", entry("A", pronunciation="/x/", audio_url="https://a/x.mp3"))
    definitions_only = FakeSource("W", entry("W"), provides={"senses"})
    thesaurus = FakeSource("T", entry("T", senses=False, synonyms=["fleeting"], antonyms=["lasting"]))
    result = make(words_file, primary, definitions_only, thesaurus).lookup("ephemeral")

    assert result.definition == "definition from A"
    assert result.synonyms == ["fleeting"] and result.antonyms == ["lasting"]
    assert result.sources == ["A", "T"]
    assert definitions_only.calls == 0  # it couldn't have filled anything


def test_related_words_found_before_definitions_are_kept(words_file):
    thesaurus = FakeSource("T", entry("T", senses=False, synonyms=["fleeting"]))
    dictionary = FakeSource("A", entry("A"))
    result = make(words_file, thesaurus, dictionary).lookup("ephemeral")
    assert result.definition == "definition from A"
    assert result.synonyms == ["fleeting"]
    assert result.sources == ["A", "T"]


def test_not_found_anywhere(words_file):
    with pytest.raises(WordNotFoundError):
        make(words_file, FakeSource("A"), FakeSource("B")).lookup("qwzxvbn")


def test_synonyms_alone_do_not_count_as_found(words_file):
    thesaurus = FakeSource("T", entry("T", senses=False, synonyms=["x"]))
    with pytest.raises(WordNotFoundError):
        make(words_file, thesaurus).lookup("qwzxvbn")


def test_not_found_with_failures_is_a_lookup_failure(words_file):
    failing = FakeSource("A", SourceError("A: server error (HTTP 500)"))
    with pytest.raises(LookupFailedError, match="HTTP 500") as info:
        make(words_file, failing, FakeSource("B")).lookup("ephemeral")
    assert len(info.value.errors) == 1


def test_cache_is_used_and_refresh_bypasses_it(words_file, tmp_path):
    source = FakeSource("A", entry("A", **COMPLETE))
    wotd = make(words_file, source, cache=JsonFileCache(tmp_path / "cache"))

    first = wotd.lookup("ephemeral")
    assert wotd.lookup("ephemeral") == first
    assert source.calls == 1
    wotd.lookup("ephemeral", refresh=True)
    assert source.calls == 2


def test_entries_built_during_failures_expire_sooner(words_file, tmp_path):
    failing = FakeSource("A", SourceError("A: server error (HTTP 500)"))
    working = FakeSource("B", entry("B", **COMPLETE))
    make(words_file, failing, working, cache=JsonFileCache(tmp_path / "cache")).lookup("ephemeral")

    record = json.loads((tmp_path / "cache" / "ephemeral.json").read_text(encoding="utf-8"))
    expires_in = datetime.fromisoformat(record["expires_at"]) - datetime.now(timezone.utc)
    assert timedelta(hours=23) < expires_in <= timedelta(days=1)


def test_for_date_looks_up_the_selected_word(words_file):
    day = date(2026, 9, 23)
    source = FakeSource("A", entry("A", **COMPLETE))
    wotd = make(words_file, source)
    assert wotd.word_for(day) == pick_word(["ephemeral", "serendipity", "laconic"], day)
    assert wotd.for_date(day).sources == ["A"]


def test_empty_word_list_is_an_error(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# nothing yet\n", encoding="utf-8")
    with pytest.raises(WordOfTheDayError, match="doesn't contain any words"):
        make(path, FakeSource("A")).today()


def test_from_env_adds_merriam_webster_only_with_a_key(words_file):
    with WordOfTheDay.from_env(words_file, None, env={}) as wotd:
        assert [s.name for s in wotd.sources] == ["Free Dictionary API", "Wiktionary", "Datamuse"]
        assert wotd.cache is None

    env = {"MW_DICTIONARY_KEY": "d", "MW_THESAURUS_KEY": "t"}
    with WordOfTheDay.from_env(words_file, "cache", env=env) as wotd:
        assert isinstance(wotd.sources[0], MerriamWebsterSource)
        assert wotd.sources[0].provides == {"senses", *FILLABLE_FIELDS}


def test_failed_sources_are_skipped_for_a_while(words_file):
    failing = FakeSource("A", SourceError("A: request failed (ReadTimeout)"))
    working = FakeSource("B", entry("B", **COMPLETE))
    wotd = make(words_file, failing, working)
    wotd.lookup("ephemeral")
    wotd.lookup("serendipity")
    assert failing.calls == 1 and working.calls == 2


def test_failed_sources_are_retried_after_the_cooldown(words_file):
    failing = FakeSource("A", SourceError("A: request failed (ReadTimeout)"))
    working = FakeSource("B", entry("B", **COMPLETE))
    wotd = WordOfTheDay(words_file, [failing, working], source_cooldown=timedelta(0))
    wotd.lookup("ephemeral")
    wotd.lookup("serendipity")
    assert failing.calls == 2


def test_a_skipped_source_means_lookup_failed_not_word_missing(words_file):
    failing = FakeSource("A", SourceError("A: server error (HTTP 503)"))
    wotd = make(words_file, failing)
    with pytest.raises(LookupFailedError):
        wotd.lookup("ephemeral")
    with pytest.raises(LookupFailedError, match="skipped after a recent failure"):
        wotd.lookup("serendipity")
