"""Free Dictionary API, Wiktionary and Datamuse."""

import httpx
import pytest
from helpers import Recorder, load_fixture

from word_of_day.errors import SourceError
from word_of_day.models import Sense
from word_of_day.sources import DatamuseSource, FreeDictionarySource, WiktionarySource


def respond(response: httpx.Response) -> Recorder:
    return Recorder(lambda request: response)


# --- Free Dictionary API ---


def test_free_dictionary_parses_entry():
    api = respond(httpx.Response(200, json=load_fixture("free_dictionary_ephemeral.json")))
    entry = FreeDictionarySource(api.client()).lookup("ephemeral")

    assert entry.senses[0] == Sense("Something which lasts for a short period of time.", "noun")
    assert entry.senses[1].examples == ["Fame is ephemeral."]
    assert entry.parts_of_speech == ["noun", "adjective"]
    assert entry.synonyms == ["transient", "Fleeting"]
    assert entry.antonyms == ["permanent"]
    assert entry.pronunciation == "/ɪˈfɛm(ə)ɹəl/"
    assert entry.audio_url.endswith("ephemeral-us.mp3")
    assert entry.source_url == "https://en.wiktionary.org/wiki/ephemeral"
    assert entry.sources == ["Free Dictionary API"]


def test_free_dictionary_404_is_not_found():
    api = respond(httpx.Response(404, json={"title": "No Definitions Found"}))
    assert FreeDictionarySource(api.client()).lookup("qwzxvbn") is None


def test_free_dictionary_outage_is_a_source_error():
    api = respond(httpx.Response(522, text="error code: 522"))
    with pytest.raises(SourceError, match="HTTP 522"):
        FreeDictionarySource(api.client()).lookup("ephemeral")


def test_network_failure_is_a_source_error():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(SourceError, match="ReadTimeout"):
        FreeDictionarySource(Recorder(handler).client()).lookup("ephemeral")


# --- Wiktionary ---


def test_wiktionary_parses_real_response():
    api = respond(httpx.Response(200, json=load_fixture("wiktionary_ephemeral.json")))
    entry = WiktionarySource(api.client()).lookup("ephemeral")

    assert entry.parts_of_speech == ["adjective", "noun"]
    assert entry.definition == "Lasting for a short period of time."
    assert entry.senses[1].definition == "Existing for only one day, as with some flowers, insects, and diseases."
    assert all("<" not in s.definition for s in entry.senses)
    assert entry.source_url == "https://en.wiktionary.org/wiki/ephemeral"


def test_wiktionary_cuts_nested_sub_senses_and_skips_other_languages():
    data = {
        "en": [
            {
                "partOfSpeech": "Verb",
                "language": "English",
                "definitions": [
                    {
                        "definition": "To move swiftly.\n<ol><li>To move <a href='/wiki/quickly'>quickly</a>.</li></ol>",
                        "parsedExamples": [{"example": "<b>Run</b>, and you might still catch the train!"}],
                    },
                    {"definition": "<span class='usage-label-sense'></span>"},
                ],
            },
            {"partOfSpeech": "Noun", "language": "Translingual", "definitions": [{"definition": "A symbol."}]},
        ]
    }
    entry = WiktionarySource(respond(httpx.Response(200, json=data)).client()).lookup("run")
    assert entry.senses == [Sense("To move swiftly.", "verb", ["Run, and you might still catch the train!"])]


def test_wiktionary_retries_in_lowercase():
    def handler(request):
        if request.url.path.endswith("/Ephemeral"):
            return httpx.Response(404)
        return httpx.Response(200, json=load_fixture("wiktionary_ephemeral.json"))

    api = Recorder(handler)
    entry = WiktionarySource(api.client()).lookup("Ephemeral")
    assert entry.word == "ephemeral"
    assert len(api.requests) == 2


# --- Datamuse ---


def test_datamuse_returns_related_words_only():
    def handler(request):
        if "rel_syn" in request.url.params:
            return httpx.Response(200, json=[{"word": "transient", "score": 3}, {"word": "ephemeral", "score": 2}])
        return httpx.Response(200, json=[{"word": "permanent", "score": 1}])

    entry = DatamuseSource(Recorder(handler).client()).lookup("ephemeral")
    assert entry.senses == []
    assert entry.synonyms == ["transient"]
    assert entry.antonyms == ["permanent"]


def test_datamuse_with_no_results_is_not_found():
    assert DatamuseSource(respond(httpx.Response(200, json=[])).client()).lookup("qwzxvbn") is None
