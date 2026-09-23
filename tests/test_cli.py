import json
from datetime import date

import pytest

from word_of_day import cli
from word_of_day.formatting import format_entry
from word_of_day.models import Sense, WordEntry
from word_of_day.selector import pick_word
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
        return WordEntry(word, [Sense(f"meaning of {word}", "noun", [f"a {word} example"])], sources=[self.name])


@pytest.fixture(autouse=True)
def stub_service(tmp_path, monkeypatch):
    """Run the CLI in an empty directory with an offline service."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "words.txt").write_text("\n".join(WORDS), encoding="utf-8")
    monkeypatch.setattr(
        WordOfTheDay, "from_env", classmethod(lambda cls, words_file, cache_dir: cls(words_file, [StubSource()]))
    )


def test_json_output_for_a_date(tmp_path, capsys):
    known = ["ephemeral", "serendipity"]
    (tmp_path / "known.txt").write_text("\n".join(known), encoding="utf-8")
    expected = pick_word(known, date(2026, 9, 23))

    assert cli.main(["--words", "known.txt", "--date", "2026-09-23", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["date"] == "2026-09-23"
    assert data["word"] == expected
    assert data["senses"][0]["definition"] == f"meaning of {expected}"


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
    assert "can't read the word list" in capsys.readouterr().err


def test_format_entry_groups_and_truncates():
    entry = WordEntry(
        "run",
        [Sense(f"verb sense {i}", "verb") for i in range(5)] + [Sense("a noun sense", "noun", ["a quick run"])],
        synonyms=["dash", "sprint"],
        pronunciation="\\ˈrən\\",
        sources=["A", "B"],
        source_url="https://example.com/run",
    )
    text = format_entry(entry, day=date(2026, 9, 23))
    assert text.splitlines()[0] == "WORD OF THE DAY · Wednesday, September 23, 2026"
    assert "run  \\ˈrən\\" in text
    assert "  3. verb sense 2" in text and "verb sense 3" not in text
    assert "  … 2 more" in text
    assert "“a quick run”" in text
    assert "Synonyms: dash, sprint" in text
    assert text.endswith("Source: A, B\nhttps://example.com/run")
