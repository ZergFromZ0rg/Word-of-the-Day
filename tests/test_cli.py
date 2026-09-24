import json
from datetime import date, timedelta

import pytest

from word_of_day import cli
from word_of_day.formatting import format_entry
from word_of_day.history import History
from word_of_day.models import Sense, WordEntry
from word_of_day.service import WordOfTheDay
from word_of_day.sources import DictionarySource

WORDS = ["ephemeral", "serendipity", "qwzxvbn"]


class StubSource(DictionarySource):
    name = "Stub"

    def __init__(self):
        super().__init__(client=None)

    def lookup(self, word):
        if word == "qwzxvbn":
            return None
        return WordEntry(
            word, [Sense(f"meaning of {word}", "noun", [f"a {word} example"])], sources=[self.name]
        )


seen: dict = {}


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """Run the CLI in an empty directory with an offline service."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "words.txt").write_text("\n".join(WORDS), encoding="utf-8")

    def from_env(cls, words_file, cache_dir, history_file, word_source=None):
        seen["word_source"] = word_source
        return cls(words_file, [StubSource()], history_file=history_file)

    seen.clear()

    monkeypatch.setattr(WordOfTheDay, "from_env", classmethod(from_env))


def test_todays_word_is_recorded(tmp_path, capsys):
    assert cli.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["senses"][0]["definition"] == f"meaning of {data['word']}"
    history = History.load(tmp_path / "history.json")
    assert history.days == {date.fromisoformat(data["date"]): data["word"]}


def test_source_option_is_passed_on(capsys):
    assert cli.main(["--word", "ephemeral", "--source", "merriam"]) == 0
    assert seen["word_source"] == "merriam"


def test_history_lists_earlier_days(tmp_path, capsys):
    History(days={date(2026, 9, 21): "laconic", date(2026, 9, 22): "serendipity"}).save(
        tmp_path / "history.json"
    )
    assert cli.main(["--history"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "2026-09-22  serendipity",
        "2026-09-21  laconic",
    ]


def test_check_lets_found_words_be_picked_again(tmp_path, capsys):
    History(not_found={"ephemeral", "qwzxvbn"}).save(tmp_path / "history.json")
    cli.main(["--check"])
    assert History.load(tmp_path / "history.json").not_found == {"qwzxvbn"}


def test_text_output_for_a_word(capsys):
    assert cli.main(["--word", "ephemeral"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("ephemeral\n")
    assert "1. meaning of ephemeral" in out


def test_unknown_word_exits_with_error(capsys):
    assert cli.main(["--word", "qwzxvbn"]) == 1
    assert "no dictionary has an entry" in capsys.readouterr().err


def test_check_reports_missing_words(capsys):
    assert cli.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "✓ ephemeral" in out and "✗ qwzxvbn" in out and "2/3 words found" in out


def test_missing_word_list(capsys):
    assert cli.main(["--words", "nope.txt"]) == 1
    assert "nope.txt" in capsys.readouterr().err


def test_quiz_without_history(capsys):
    assert cli.main(["--quiz"]) == 0
    assert "No earlier words yet" in capsys.readouterr().out


def test_quiz_reveals_a_recent_word(tmp_path, capsys):
    yesterday = date.today() - timedelta(days=1)
    History(days={yesterday: "serendipity"}).save(tmp_path / "history.json")
    assert cli.main(["--quiz"]) == 0
    out = capsys.readouterr().out
    assert "the word was: serendipity" in out
    assert "1. meaning of serendipity" in out


def test_import_mw_wotd_adds_new_words(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_feed_words", lambda client: ["compendious", "Ephemeral"])
    assert cli.main(["--import-mw-wotd"]) == 0
    assert "Added 1 word(s)" in capsys.readouterr().out
    assert (tmp_path / "words.txt").read_text(encoding="utf-8").splitlines()[-1] == "compendious"

    assert cli.main(["--import-mw-wotd"]) == 0
    assert "Nothing new" in capsys.readouterr().out


def test_format_entry():
    entry = WordEntry(
        "run",
        [Sense(f"verb sense {i}", "verb") for i in range(5)]
        + [Sense("a noun sense", "noun", ["a quick run"])],
        synonyms=["dash", "sprint"],
        pronunciation="\\ˈrən\\",
        etymology="Middle English rinnen, from Old English rinnan",
        first_known_use="before the 12th century",
        sources=["A", "B"],
        source_url="https://example.com/run",
    )
    text = format_entry(entry, day=date(2026, 9, 23))
    assert text.splitlines()[0] == "WORD OF THE DAY · Wednesday, September 23, 2026"
    assert "run  \\ˈrən\\" in text
    assert "  3. verb sense 2" in text and "verb sense 3" not in text
    assert "  … 2 more" in text
    assert "“a quick run”" in text
    assert "Origin: Middle English rinnen, from Old English rinnan" in text
    assert "First known use: before the 12th century" in text
    assert "Synonyms: dash, sprint" in text
    assert text.endswith("Source: A, B\nhttps://example.com/run")
