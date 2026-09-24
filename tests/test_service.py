import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from word_of_day.cache import JsonFileCache
from word_of_day.errors import (
    LookupFailedError,
    SourceError,
    WordNotFoundError,
    WordOfTheDayError,
)
from word_of_day.history import History
from word_of_day.models import FILLABLE_FIELDS, Sense, WordEntry
from word_of_day.service import WordOfTheDay
from word_of_day.sources import DictionarySource, MerriamWebsterSource

TODAY = date(2026, 9, 23)
WORDS = ["ephemeral", "serendipity", "laconic"]
COMPLETE = dict(
    synonyms=["fleeting"], antonyms=["lasting"], pronunciation="/x/", audio_url="https://a/x.mp3"
)


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


class KnownWords(DictionarySource):
    """A complete dictionary for a fixed set of words."""

    name = "Known"

    def __init__(self, *known):
        super().__init__(client=None)
        self.known = set(known)
        self.looked_up = []

    def lookup(self, word):
        self.looked_up.append(word)
        if word not in self.known:
            return None
        return WordEntry(word, [Sense(f"meaning of {word}")], sources=[self.name], **COMPLETE)


def entry(source, *, senses=True, **fields):
    return WordEntry(
        word="ephemeral",
        senses=[Sense(f"definition from {source}")] if senses else [],
        sources=[source],
        **fields,
    )


@pytest.fixture
def words_file(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("ephemeral\nserendipity\nlaconic\n", encoding="utf-8")
    return path


def make(words_file, *sources, cache=None, history_file=None):
    wotd = WordOfTheDay(words_file, sources, cache, history_file=history_file)
    wotd.current_date = lambda: TODAY
    return wotd


# --- Combining sources ---


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
    thesaurus = FakeSource(
        "T", entry("T", senses=False, synonyms=["fleeting"], antonyms=["lasting"])
    )
    result = make(words_file, primary, definitions_only, thesaurus).lookup("ephemeral")

    assert result.definition == "definition from A"
    assert result.synonyms == ["fleeting"] and result.antonyms == ["lasting"]
    assert result.sources == ["A", "T"]
    assert definitions_only.calls == 0  # it couldn't have filled anything


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


# --- Cache ---


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


# --- Choosing and history ---


def test_todays_word_survives_edits_to_the_list(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    source = KnownWords("ephemeral", "serendipity", "laconic", "compendious", "nemesis")
    wotd = make(words_file, source, history_file=history_file)

    word = wotd.today().word
    assert History.load(history_file).days == {TODAY: word}

    with words_file.open("a", encoding="utf-8") as f:
        f.write("compendious\nnemesis\n")
    assert wotd.today().word == word
    assert wotd.word_for(TODAY) == word


def test_removing_todays_word_replaces_it(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    wotd = make(
        words_file, KnownWords("ephemeral", "serendipity", "laconic"), history_file=history_file
    )
    word = wotd.today().word

    remaining = [w for w in ("ephemeral", "serendipity", "laconic") if w != word]
    words_file.write_text("\n".join(remaining), encoding="utf-8")
    replacement = wotd.today().word
    assert replacement in remaining
    assert History.load(history_file).days[TODAY] == replacement


def test_unknown_words_are_skipped_and_remembered(tmp_path):
    words_file = tmp_path / "words.txt"
    words_file.write_text("qwzxvbn\nzzyzzx-nope\nephemeral\n", encoding="utf-8")
    history_file = tmp_path / "history.json"
    source = KnownWords("ephemeral")
    wotd = make(words_file, source, history_file=history_file)

    assert wotd.today().word == "ephemeral"
    history = History.load(history_file)
    skipped = set(source.looked_up) - {"ephemeral"}
    assert history.not_found == skipped
    assert history.days == {TODAY: "ephemeral"}

    # Known-bad words are never picked again.
    for offset in range(1, 10):
        assert wotd.word_for(TODAY + timedelta(days=offset)) not in skipped


def test_no_findable_words_is_an_error_and_is_remembered(tmp_path):
    words_file = tmp_path / "words.txt"
    words_file.write_text("qwzxvbn\nzzyzzx-nope\n", encoding="utf-8")
    history_file = tmp_path / "history.json"
    with pytest.raises(WordOfTheDayError):
        make(words_file, KnownWords(), history_file=history_file).today()
    assert History.load(history_file).not_found == {"qwzxvbn", "zzyzzx-nope"}

    source = KnownWords()
    with pytest.raises(WordOfTheDayError, match="every word is marked as not found"):
        make(words_file, source, history_file=history_file).today()
    assert source.looked_up == []


def test_gives_up_after_several_unknown_words(tmp_path):
    words_file = tmp_path / "words.txt"
    words_file.write_text("\n".join(f"nope{i}" for i in range(8)), encoding="utf-8")
    source = KnownWords()
    with pytest.raises(WordOfTheDayError, match="no dictionary has any of"):
        make(words_file, source).today()
    assert len(source.looked_up) == 5


def test_other_dates_are_not_recorded(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    wotd = make(
        words_file, KnownWords("ephemeral", "serendipity", "laconic"), history_file=history_file
    )
    wotd.for_date(TODAY + timedelta(days=3))
    wotd.for_date(TODAY - timedelta(days=3))
    assert History.load(history_file).days == {}


def test_recent_lists_earlier_days(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    History(days={TODAY - timedelta(days=2): "laconic", TODAY: "ephemeral"}).save(history_file)
    wotd = make(words_file, KnownWords(), history_file=history_file)
    assert wotd.recent() == [(TODAY - timedelta(days=2), "laconic")]


def test_without_a_history_file_picks_are_kept_in_memory(words_file):
    wotd = make(words_file, KnownWords("ephemeral", "serendipity", "laconic"))
    word = wotd.today().word
    words_file.write_text("ephemeral\nserendipity\nlaconic\ncompendious\n", encoding="utf-8")
    assert wotd.today().word == word


def test_empty_word_list_is_an_error(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# nothing yet\n", encoding="utf-8")
    with pytest.raises(WordOfTheDayError, match="doesn't contain any words"):
        make(path, FakeSource("A")).today()


# --- Time zone and configuration ---


def test_time_zone_decides_the_date(words_file):
    wotd = WordOfTheDay(words_file, [], timezone="Pacific/Kiritimati")
    assert wotd.current_date() == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()


def test_unknown_time_zone_is_an_error(words_file):
    with pytest.raises(WordOfTheDayError, match="unknown time zone"):
        WordOfTheDay(words_file, [], timezone="Mars/Olympus_Mons")


def test_from_env(words_file):
    with WordOfTheDay.from_env(words_file, None, None, env={}) as wotd:
        assert [s.name for s in wotd.sources] == ["Wiktionary", "Datamuse"]
        assert wotd.cache is None and wotd.history_file is None and wotd.timezone is None

    env = {"MW_DICTIONARY_KEY": "d", "MW_THESAURUS_KEY": "t", "WOTD_TIMEZONE": "America/Toronto"}
    with WordOfTheDay.from_env(words_file, env=env) as wotd:
        assert isinstance(wotd.sources[0], MerriamWebsterSource)
        assert wotd.sources[0].provides == {"senses", *FILLABLE_FIELDS}
        assert wotd.timezone == ZoneInfo("America/Toronto")


# --- Cache after changing sources ---


def test_cache_from_other_sources_is_not_reused(words_file, tmp_path):
    cache = JsonFileCache(tmp_path / "cache")
    free = FakeSource("Free", entry("Free"), provides={"senses"})
    WordOfTheDay(words_file, [free], cache).lookup("ephemeral")

    # Same source set: served from the cache.
    same = FakeSource("Free", entry("Free"), provides={"senses"})
    WordOfTheDay(words_file, [same], cache).lookup("ephemeral")
    assert same.calls == 0

    # A Merriam-Webster key was added: fetched again instead of showing the old entry.
    upgraded = FakeSource("Merriam-Webster", entry("Merriam-Webster", **COMPLETE))
    result = WordOfTheDay(words_file, [upgraded, free], cache).lookup("ephemeral")
    assert upgraded.calls == 1 and result.sources == ["Merriam-Webster"]


# --- Forgetting words that weren't found ---


def test_clear_not_found(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    History(not_found={"ephemeral", "laconic", "qwzxvbn"}).save(history_file)
    wotd = make(words_file, KnownWords(), history_file=history_file)
    wotd.clear_not_found(["Ephemeral"])
    assert History.load(history_file).not_found == {"laconic", "qwzxvbn"}
    wotd.clear_not_found()
    assert History.load(history_file).not_found == set()


# --- Merriam-Webster's own Word of the Day as the source ---

FEED_XML = (
    "<rss><channel>"
    "<item><title>compendious</title><link>https://m.com/wotd/compendious-2026-09-23</link></item>"
    "<item><title>nemesis</title><link>https://m.com/wotd/nemesis-2026-09-22</link></item>"
    "</channel></rss>"
)


def merriam_mode(words_file, source, feed=None, history_file=None):
    calls = []

    def handler(request):
        calls.append(request)
        if feed is None:
            return httpx.Response(503)
        return httpx.Response(200, text=feed)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    wotd = WordOfTheDay(
        words_file, [source], history_file=history_file, client=client, word_source="merriam"
    )
    wotd.current_date = lambda: TODAY
    return wotd, calls


def test_merriam_mode_uses_their_word_for_the_day(words_file, tmp_path):
    source = KnownWords("compendious", "nemesis", "ephemeral", "serendipity", "laconic")
    wotd, calls = merriam_mode(words_file, source, FEED_XML, tmp_path / "history.json")
    assert wotd.today().word == "compendious"
    assert wotd.for_date(TODAY - timedelta(days=1)).word == "nemesis"
    assert len(calls) == 1  # the feed is fetched once, then remembered
    assert History.load(tmp_path / "history.json").days == {TODAY: "compendious"}


def test_merriam_mode_needs_no_word_list(tmp_path):
    missing = tmp_path / "nope.txt"
    wotd, _ = merriam_mode(missing, KnownWords("compendious"), FEED_XML)
    assert wotd.today().word == "compendious"


def test_merriam_mode_falls_back_to_the_list(words_file):
    source = KnownWords("ephemeral", "serendipity", "laconic")
    # The feed is down.
    wotd, _ = merriam_mode(words_file, source, feed=None)
    assert wotd.today().word in WORDS
    # The feed doesn't have today yet.
    old_feed = FEED_XML.replace("2026-09-23", "2026-09-20")
    wotd, _ = merriam_mode(words_file, source, old_feed)
    assert wotd.today().word in WORDS
    # Their word isn't in any dictionary we can reach.
    wotd, _ = merriam_mode(words_file, KnownWords("ephemeral", "serendipity", "laconic"), FEED_XML)
    assert wotd.today().word in WORDS


def test_merriam_mode_without_feed_or_list_is_an_error(tmp_path):
    wotd, _ = merriam_mode(tmp_path / "nope.txt", KnownWords(), feed=None)
    with pytest.raises(WordOfTheDayError, match="isn't available"):
        wotd.today()


def test_todays_word_stays_when_switching_source(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    source = KnownWords("compendious", "ephemeral", "serendipity", "laconic")
    listed = make(words_file, source, history_file=history_file).today().word
    assert listed in WORDS
    wotd, _ = merriam_mode(words_file, source, FEED_XML, history_file)
    assert wotd.today().word == listed  # already shown today; Merriam-Webster starts tomorrow
    assert wotd.for_date(TODAY + timedelta(days=0)).word == listed


def test_unknown_word_source(words_file):
    with pytest.raises(WordOfTheDayError, match="unknown word source"):
        WordOfTheDay(words_file, [], word_source="random")


def test_from_env_reads_the_word_source(words_file):
    with WordOfTheDay.from_env(words_file, None, None, env={"WOTD_WORD_SOURCE": "merriam"}) as w:
        assert w.word_source == "merriam"
    with WordOfTheDay.from_env(
        words_file, None, None, env={"WOTD_WORD_SOURCE": "merriam"}, word_source="list"
    ) as w:
        assert w.word_source == "list"


def test_stand_in_word_is_replaced_once_merriam_posts_theirs(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    source = KnownWords("compendious", "ephemeral", "serendipity", "laconic")
    feed = {"xml": FEED_XML.replace("2026-09-23", "2026-09-20")}  # nothing for today yet
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=feed["xml"]))
    )
    wotd = WordOfTheDay(
        words_file, [source], history_file=history_file, client=client, word_source="merriam"
    )
    wotd.current_date = lambda: TODAY

    standin = wotd.today().word
    assert standin in WORDS
    assert History.load(history_file).provisional == {TODAY}
    assert wotd.today().word == standin  # stable while the feed has nothing

    feed["xml"] = FEED_XML  # Merriam-Webster posts today's word
    wotd._feed_cache = None
    assert wotd.today().word == "compendious"
    saved = History.load(history_file)
    assert saved.days[TODAY] == "compendious" and saved.provisional == set()
    assert wotd.today().word == "compendious"


def test_two_processes_do_not_overwrite_each_others_history(words_file, tmp_path):
    history_file = tmp_path / "history.json"
    a = make(
        words_file, KnownWords("ephemeral", "serendipity", "laconic"), history_file=history_file
    )
    b = make(words_file, KnownWords(), history_file=history_file)
    b_view = History.load(history_file)  # what b saw before a acted
    word = a.today().word
    b.clear_not_found(["something"])  # b writes after having read the older file
    assert History.load(history_file).days == {TODAY: word}
    assert b_view.days == {}
