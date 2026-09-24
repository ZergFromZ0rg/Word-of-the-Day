import json
import threading
from datetime import date

from word_of_day.history import History


def test_round_trip(tmp_path):
    path = tmp_path / "data" / "history.json"
    history = History(
        days={date(2026, 9, 23): "perspicacious", date(2026, 9, 22): "déjà vu"},
        not_found={"qwzxvbn"},
        provisional={date(2026, 9, 23)},
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


def test_modify_keeps_changes_made_since_it_was_loaded(tmp_path):
    path = tmp_path / "history.json"
    stale = History.load(path)  # a process that read the file early
    History.modify(path, lambda h: h.not_found.add("qwzxvbn"))  # another process writes
    History.modify(path, lambda h: h.days.update({date(2026, 9, 23): "laconic"}))
    assert stale.days == {}
    assert History.load(path) == History(days={date(2026, 9, 23): "laconic"}, not_found={"qwzxvbn"})


def test_modify_is_safe_with_concurrent_writers(tmp_path):
    path = tmp_path / "history.json"

    def add(n):
        for i in range(10):
            History.modify(path, lambda h, word=f"w{n}-{i}": h.not_found.add(word))

    threads = [threading.Thread(target=add, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(History.load(path).not_found) == 60
