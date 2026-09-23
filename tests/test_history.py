import json
from datetime import date

from word_of_day.history import History


def test_round_trip(tmp_path):
    path = tmp_path / "data" / "history.json"
    history = History(
        days={date(2026, 9, 23): "perspicacious", date(2026, 9, 22): "déjà vu"},
        not_found={"qwzxvbn"},
    )
    history.save(path)
    assert History.load(path) == history

    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(data["days"]) == ["2026-09-22", "2026-09-23"]  # sorted, readable
    assert not list(path.parent.glob("*.tmp"))


def test_missing_or_corrupt_file_is_empty(tmp_path):
    assert History.load(tmp_path / "nope.json") == History()
    corrupt = tmp_path / "history.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert History.load(corrupt) == History()


def test_before_is_most_recent_first():
    history = History(
        days={
            date(2026, 9, 20): "a",
            date(2026, 9, 22): "b",
            date(2026, 9, 23): "c",
            date(2026, 9, 25): "future",
        }
    )
    assert history.before(date(2026, 9, 23)) == [(date(2026, 9, 22), "b"), (date(2026, 9, 20), "a")]
