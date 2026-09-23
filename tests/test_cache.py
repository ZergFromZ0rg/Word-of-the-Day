import json
from datetime import timedelta

from word_of_day.cache import JsonFileCache
from word_of_day.models import Sense, WordEntry

ENTRY = WordEntry("déjà vu", [Sense("a feeling of having already experienced the present", "noun")], sources=["X"])


def test_round_trip(tmp_path):
    cache = JsonFileCache(tmp_path)
    assert cache.get("déjà vu") is None
    cache.set("déjà vu", ENTRY)
    assert cache.get("déjà vu") == ENTRY
    assert (tmp_path / "déjà_vu.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_expired_entries_are_misses(tmp_path):
    cache = JsonFileCache(tmp_path)
    cache.set("déjà vu", ENTRY, max_age=timedelta(seconds=-1))
    assert cache.get("déjà vu") is None


def test_no_max_age_never_expires(tmp_path):
    cache = JsonFileCache(tmp_path, max_age=None)
    cache.set("déjà vu", ENTRY)
    record = json.loads((tmp_path / "déjà_vu.json").read_text(encoding="utf-8"))
    assert record["expires_at"] is None
    assert cache.get("déjà vu") == ENTRY


def test_different_word_with_same_file_name_is_a_miss(tmp_path):
    cache = JsonFileCache(tmp_path)
    cache.set("déjà vu", ENTRY)
    assert cache.get("déjà_vu") is None


def test_corrupt_or_old_files_are_misses(tmp_path):
    cache = JsonFileCache(tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert cache.get("broken") is None

    cache.set("old", ENTRY)
    path = tmp_path / "old.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**record, "version": 0}), encoding="utf-8")
    assert cache.get("old") is None
