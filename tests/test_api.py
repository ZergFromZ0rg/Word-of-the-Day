import datetime as dt

import pytest
from fastapi.testclient import TestClient

from word_of_day import __version__
from word_of_day.api import app_from_env, create_app
from word_of_day.errors import SourceError
from word_of_day.history import History
from word_of_day.models import Sense, WordEntry
from word_of_day.service import WordOfTheDay
from word_of_day.sources import DictionarySource

TODAY = dt.date(2026, 9, 23)
WORDS = ["ephemeral", "serendipity", "laconic"]


class Dictionary(DictionarySource):
    name = "Test"

    def __init__(self, known=WORDS, error=None):
        super().__init__(client=None)
        self.known = set(known)
        self.error = error

    def lookup(self, word):
        if self.error:
            raise self.error
        if word not in self.known:
            return None
        return WordEntry(word, [Sense(f"meaning of {word}", "noun")], sources=[self.name])


@pytest.fixture
def make_client(tmp_path):
    """Build a TestClient around an offline WordOfTheDay whose "today" is TODAY."""

    def make(source=None, words=WORDS):
        words_file = tmp_path / "words.txt"
        words_file.write_text("\n".join(words), encoding="utf-8")
        wotd = WordOfTheDay(
            words_file, [source or Dictionary()], history_file=tmp_path / "history.json"
        )
        wotd.current_date = lambda: TODAY
        return TestClient(create_app(wotd))

    return make


def test_word_of_the_day(make_client, tmp_path):
    with make_client() as client:
        first = client.get("/word-of-the-day")
        second = client.get("/word-of-the-day")
    assert first.status_code == 200
    data = first.json()
    assert data["date"] == "2026-09-23"
    assert data["entry"]["word"] in WORDS
    assert data["entry"]["senses"][0] == {
        "definition": f"meaning of {data['entry']['word']}",
        "part_of_speech": "noun",
        "examples": [],
    }
    assert second.json() == data
    assert History.load(tmp_path / "history.json").days == {TODAY: data["entry"]["word"]}


def test_word_for_a_date(make_client):
    with make_client() as client:
        response = client.get("/word-of-the-day/2026-12-25")
        assert response.status_code == 200
        assert response.json()["date"] == "2026-12-25"
        assert client.get("/word-of-the-day/25-12-2026").status_code == 422


def test_lookup_any_word(make_client):
    with make_client(Dictionary(known=["déjà vu"])) as client:
        assert (
            client.get("/words/déjà vu").json()["senses"][0]["definition"] == "meaning of déjà vu"
        )
        missing = client.get("/words/qwzxvbn")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "no dictionary has an entry for 'qwzxvbn'"}


def test_dictionary_outage_is_a_bad_gateway(make_client):
    source = Dictionary(error=SourceError("Test: server error (HTTP 503)"))
    with make_client(source) as client:
        response = client.get("/words/ephemeral")
    assert response.status_code == 502
    assert "HTTP 503" in response.json()["detail"]


def test_no_usable_words_is_a_server_error(make_client):
    with make_client(Dictionary(known=[])) as client:
        response = client.get("/word-of-the-day")
    assert response.status_code == 500
    assert "no usable words left" in response.json()["detail"]


def test_recent(make_client, tmp_path):
    History(
        days={
            TODAY - dt.timedelta(days=2): "laconic",
            TODAY - dt.timedelta(days=1): "serendipity",
            TODAY: "ephemeral",
        }
    ).save(tmp_path / "history.json")
    with make_client() as client:
        assert client.get("/recent").json() == [
            {"date": "2026-09-22", "word": "serendipity"},
            {"date": "2026-09-21", "word": "laconic"},
        ]
        assert len(client.get("/recent?days=1").json()) == 1
        assert client.get("/recent?days=0").status_code == 422


def test_health(make_client, tmp_path):
    with make_client() as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "version": __version__,
            "today": "2026-09-23",
            "words": 3,
        }
        (tmp_path / "words.txt").unlink()
        broken = client.get("/health")
    assert broken.status_code == 500
    assert "words.txt" in broken.json()["detail"]


def test_cors_allows_any_origin_by_default(make_client):
    with make_client() as client:
        response = client.get("/health", headers={"Origin": "http://homelab.local:3000"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_docs_list_the_endpoints(make_client):
    with make_client() as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {
        "/word-of-the-day",
        "/word-of-the-day/{day}",
        "/words/{word}",
        "/recent",
        "/health",
    }


def test_app_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here
    (tmp_path / "list.txt").write_text("ephemeral\nlaconic\n", encoding="utf-8")
    monkeypatch.setenv("WOTD_WORDS_FILE", "list.txt")
    monkeypatch.setenv("WOTD_CORS_ORIGINS", "http://homelab.local:3000, http://localhost:3000")
    monkeypatch.delenv("MW_DICTIONARY_KEY", raising=False)

    with TestClient(app_from_env()) as client:
        allowed = client.get("/health", headers={"Origin": "http://localhost:3000"})
        blocked = client.get("/health", headers={"Origin": "http://evil.example"})
    assert allowed.json()["words"] == 2
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in blocked.headers
