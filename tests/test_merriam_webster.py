import httpx
import pytest
from helpers import Recorder, load_fixture

from word_of_day.errors import SourceError
from word_of_day.models import Sense
from word_of_day.sources.merriam_webster import (
    MerriamWebsterSource,
    audio_url,
    clean_markup,
    matching_entries,
    parse_dictionary,
)

DICTIONARY = load_fixture("mw_collegiate_ephemeral.json")
THESAURUS = load_fixture("mw_thesaurus_ephemeral.json")


def mw_api(dictionary=DICTIONARY, thesaurus=THESAURUS) -> Recorder:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/collegiate/" in request.url.path:
            return (
                dictionary
                if isinstance(dictionary, httpx.Response)
                else httpx.Response(200, json=dictionary)
            )
        return (
            thesaurus
            if isinstance(thesaurus, httpx.Response)
            else httpx.Response(200, json=thesaurus)
        )

    return Recorder(handler)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("{bc}lasting a very short time ", "lasting a very short time"),
        ("{bc}{sx|bounce||}, {sx|rebound||} ", "bounce, rebound"),
        ("{bc}a state of inactivity {bc}{sx|suspension||} ", "a state of inactivity; suspension"),
        ("{bc}{sx|dance||3}", "dance"),
        ("{bc}a {a_link|backward} somersault", "a backward somersault"),
        ("{bc}lasting {dx}compare {dxt|transient||}{/dx}", "lasting"),
        ("an {it}ephemeral{/it} fever", "an ephemeral fever"),
        ("{ldquo}quoted{rdquo} {ds||1||}text", "“quoted” text"),
        ("H{inf}2{/inf}O", "H2O"),
    ],
)
def test_clean_markup(raw, expected):
    assert clean_markup(raw) == expected


@pytest.mark.parametrize(
    "name, folder",
    [
        ("bixtest01", "bix"),
        ("ggmail01", "gg"),
        ("3d000001", "number"),
        ("_test01", "number"),
        ("epheme02", "e"),
    ],
)
def test_audio_folder_rules(name, folder):
    assert (
        audio_url(name)
        == f"https://media.merriam-webster.com/audio/prons/en/us/mp3/{folder}/{name}.mp3"
    )


def test_parses_senses_examples_and_pronunciation():
    entry = parse_dictionary(matching_entries(DICTIONARY, "ephemeral"))
    assert entry.word == "ephemeral"
    assert entry.senses == [
        Sense("lasting one day only", "adjective", ["an ephemeral fever"]),
        Sense(
            "lasting a very short time",
            "adjective",
            ["ephemeral pleasures", "the ephemeral nature of fame — A. Writer, A Book, 1999"],
        ),
        Sense("something ephemeral: such as", "noun"),
        Sense("an ephemeron", "noun"),
        Sense(
            "a printed item meant to be discarded — usually used in plural",
            "noun",
            ["collectors of ephemerals"],
        ),
        Sense(
            "a short-lived plant; "
            "specifically one that completes its life cycle in a single season",
            "noun",
        ),
    ]
    assert entry.pronunciation == "\\i-ˈfem-rəl\\"
    assert entry.audio_url.endswith("/mp3/e/epheme02.mp3")
    assert entry.source_url == "https://www.merriam-webster.com/dictionary/ephemeral"
    # Formatting removed, "more at" cross-reference and supplemental note dropped.
    assert entry.etymology == "Greek ephēmeros lasting a day, daily, from epi- + hēmera day"
    assert entry.first_known_use == "1576"


def test_lookup_combines_dictionary_and_thesaurus():
    api = mw_api()
    entry = MerriamWebsterSource(api.client(), "dict-key", "thes-key").lookup("ephemeral")

    assert entry.sources == ["Merriam-Webster"]
    assert entry.synonyms[:3] == ["evanescent", "fleeting", "fugitive"]
    assert (
        "brief" in entry.synonyms
        and "Fleeting" not in entry.synonyms
        and "ephemeral" not in entry.synonyms
    )
    assert entry.antonyms == ["enduring", "lasting", "permanent", "perpetual"]
    assert [r.url.params["key"] for r in api.requests] == ["dict-key", "thes-key"]


def test_without_thesaurus_key_only_the_dictionary_is_called():
    api = mw_api()
    source = MerriamWebsterSource(api.client(), "dict-key")
    entry = source.lookup("ephemeral")
    assert entry.synonyms == []
    assert len(api.requests) == 1
    assert "synonyms" not in source.provides


def test_spelling_suggestions_mean_not_found():
    api = mw_api(dictionary=["ephemera", "ephemerals", "ephemeron"])
    assert MerriamWebsterSource(api.client(), "key", "key").lookup("ephemerel") is None
    assert len(api.requests) == 1


def test_invalid_key_is_a_source_error_without_the_key():
    api = mw_api(
        dictionary=httpx.Response(200, text="Invalid API key. Not subscribed for this reference.")
    )
    with pytest.raises(SourceError, match="Invalid API key") as info:
        MerriamWebsterSource(api.client(), "secret-key").lookup("ephemeral")
    assert "secret-key" not in str(info.value)


def test_rate_limit_is_a_source_error():
    api = mw_api(dictionary=httpx.Response(429))
    with pytest.raises(SourceError, match="rate limit"):
        MerriamWebsterSource(api.client(), "key").lookup("ephemeral")


def test_thesaurus_failure_keeps_the_definitions():
    api = mw_api(thesaurus=httpx.Response(500))
    entry = MerriamWebsterSource(api.client(), "key", "key").lookup("ephemeral")
    assert entry.senses and entry.synonyms == []


def test_inflected_form_uses_the_base_word():
    data = [
        {"meta": {"id": "run:1"}, "fl": "verb", "shortdef": ["to go faster than a walk"]},
        {"meta": {"id": "run:2"}, "fl": "noun", "shortdef": ["an act or the activity of running"]},
        {"meta": {"id": "runner"}, "fl": "noun", "shortdef": ["one that runs"]},
    ]
    entry = parse_dictionary(matching_entries(data, "ran"))
    assert entry.word == "run"
    assert [s.part_of_speech for s in entry.senses] == ["verb", "noun"]


def test_cross_reference_only_entry():
    data = [
        {
            "meta": {"id": "baloney"},
            "fl": "noun",
            "cxs": [{"cxl": "less common spelling of", "cxtis": [{"cxt": "bologna"}]}],
        }
    ]
    entry = parse_dictionary(matching_entries(data, "baloney"))
    assert entry.senses == [Sense("less common spelling of bologna", "noun")]
