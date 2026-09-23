from datetime import date, timedelta

import pytest

from word_of_day.selector import load_words, pick_word

WORDS = ["serendipity", "ephemeral", "ubiquitous", "mellifluous", "laconic", "halcyon", "quixotic"]


def days(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def test_load_words_skips_comments_blanks_and_duplicates(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# my words\n\nSerendipity\n  ephemeral  \nserendipity\ndéjà   vu\n# end\n", encoding="utf-8")
    assert load_words(path) == ["Serendipity", "ephemeral", "déjà vu"]


def test_same_day_always_gives_same_word():
    day = date(2026, 9, 23)
    assert pick_word(WORDS, day) == pick_word(list(WORDS), day)


def test_file_order_does_not_matter():
    for day in days(date(2026, 1, 1), 30):
        assert pick_word(WORDS, day) == pick_word(list(reversed(WORDS)), day)


def test_every_word_appears_once_per_cycle():
    n = len(WORDS)
    for cycle in range(100, 110):
        first_day = date.fromordinal(cycle * n)
        picks = [pick_word(WORDS, day) for day in days(first_day, n)]
        assert sorted(picks) == sorted(WORDS)


@pytest.mark.parametrize("words", [WORDS, WORDS[:3], WORDS[:2]])
def test_never_the_same_word_two_days_running(words):
    picks = [pick_word(words, day) for day in days(date(2020, 1, 1), 3000)]
    assert all(a != b for a, b in zip(picks, picks[1:]))


def test_seed_changes_the_order():
    period = days(date(2026, 1, 1), 60)
    assert [pick_word(WORDS, d) for d in period] != [pick_word(WORDS, d, seed="other") for d in period]


def test_single_word_list():
    assert pick_word(["solo"], date(2026, 9, 23)) == "solo"


def test_empty_list_is_an_error():
    with pytest.raises(ValueError):
        pick_word([], date(2026, 9, 23))
