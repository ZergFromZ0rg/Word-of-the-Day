from datetime import date, timedelta

import pytest

from word_of_day.selector import add_words, choose_word, load_words

WORDS = ["serendipity", "ephemeral", "ubiquitous", "mellifluous", "laconic", "halcyon", "quixotic"]
START = date(2026, 1, 1)


def simulate(words, days, history=None, start=START):
    """Choose and record a word for each day in turn, like a daily run would."""
    history = dict(history or {})
    for offset in range(days):
        day = start + timedelta(days=offset)
        history[day] = choose_word(words, history, day)
    return history


# --- Reading and writing the list ---


def test_load_words_skips_comments_blanks_and_duplicates(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text(
        "# my words\n\nSerendipity\n  ephemeral  \nserendipity\ndéjà   vu\n# end\n",
        encoding="utf-8",
    )
    assert load_words(path) == ["Serendipity", "ephemeral", "déjà vu"]


def test_add_words_appends_only_new_ones(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# list\nephemeral\nlaconic", encoding="utf-8")  # no trailing newline
    assert add_words(path, ["Laconic", "compendious", "nemesis", "compendious"]) == [
        "compendious",
        "nemesis",
    ]
    assert path.read_text(encoding="utf-8") == "# list\nephemeral\nlaconic\ncompendious\nnemesis\n"
    assert add_words(path, ["nemesis"]) == []


def test_add_words_creates_the_file(tmp_path):
    path = tmp_path / "words.txt"
    assert add_words(path, ["ephemeral"]) == ["ephemeral"]
    assert load_words(path) == ["ephemeral"]


# --- Choosing ---


def test_same_inputs_give_the_same_word():
    history = simulate(WORDS, 3)
    day = START + timedelta(days=3)
    assert choose_word(WORDS, history, day) == choose_word(list(WORDS), dict(history), day)


def test_file_order_does_not_matter():
    assert simulate(WORDS, 20) == simulate(list(reversed(WORDS)), 20)


def test_unused_words_come_first():
    history = simulate(WORDS, len(WORDS))
    assert sorted(history.values()) == sorted(WORDS)


def test_never_the_same_word_two_days_running():
    for words in (WORDS, WORDS[:3], WORDS[:2]):
        picks = list(simulate(words, 300).values())
        assert all(a != b for a, b in zip(picks, picks[1:], strict=False))


def test_after_a_full_round_recent_words_wait():
    history = simulate(WORDS, len(WORDS))
    most_recent = [w for _, w in sorted(history.items())][-(len(WORDS) // 2 + 1) :]
    next_day = START + timedelta(days=len(WORDS))
    assert choose_word(WORDS, history, next_day) not in most_recent


def test_new_words_are_used_next():
    history = simulate(WORDS, 10)
    grown = [*WORDS, "compendious"]
    assert choose_word(grown, history, START + timedelta(days=10)) == "compendious"


def test_the_day_being_chosen_is_ignored_in_history():
    day = START
    assert choose_word(WORDS, {day: "ephemeral"}, day) == choose_word(WORDS, {}, day)


def test_excluded_words_are_never_chosen():
    history = simulate(WORDS, 30)
    excluded = {"serendipity", "LACONIC"}
    for offset in range(30, 60):
        word = choose_word(WORDS, history, START + timedelta(days=offset), exclude=excluded)
        assert word.casefold() not in {"serendipity", "laconic"}


def test_seed_changes_the_choice():
    days = [START + timedelta(days=i) for i in range(20)]
    assert [choose_word(WORDS, {}, d) for d in days] != [
        choose_word(WORDS, {}, d, seed="other") for d in days
    ]


def test_nothing_to_choose_from():
    with pytest.raises(ValueError):
        choose_word([], {}, START)
    with pytest.raises(ValueError):
        choose_word(["ephemeral"], {}, START, exclude=["ephemeral"])
