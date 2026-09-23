from word_of_day.models import Sense, WordEntry, unique


def make_entry(**overrides) -> WordEntry:
    fields = dict(
        word="ephemeral",
        senses=[
            Sense("lasting a very short time", "adjective", ["ephemeral pleasures"]),
            Sense("something short-lived", "noun"),
            Sense("lasting one day only", "adjective", ["an ephemeral fever"]),
        ],
        sources=["A"],
    )
    return WordEntry(**{**fields, **overrides})


def test_unique_is_case_insensitive_and_keeps_first_spelling():
    assert unique(["Fleeting", " fleeting", "", "brief", "BRIEF"]) == ["Fleeting", "brief"]


def test_unique_exclude_and_limit():
    assert unique(["ephemeral", "a", "b", "c"], exclude=["Ephemeral"], limit=2) == ["a", "b"]


def test_convenience_properties():
    entry = make_entry()
    assert entry.definition == "lasting a very short time"
    assert entry.parts_of_speech == ["adjective", "noun"]
    assert entry.examples == ["ephemeral pleasures", "an ephemeral fever"]
    assert make_entry(senses=[]).definition is None


def test_fill_missing_only_touches_empty_fields():
    entry = make_entry(synonyms=["fleeting"], pronunciation=r"\i-ˈfem-rəl\\")
    other = make_entry(
        senses=[Sense("other definition")],
        synonyms=["transient"],
        antonyms=["permanent"],
        pronunciation="/ɪˈfɛm(ə)ɹəl/",
        audio_url="https://example.com/a.mp3",
        sources=["B"],
    )
    filled = entry.fill_missing_from(other)
    assert filled.senses == entry.senses
    assert filled.synonyms == ["fleeting"]
    assert filled.pronunciation == entry.pronunciation
    assert filled.antonyms == ["permanent"]
    assert filled.audio_url == "https://example.com/a.mp3"
    assert filled.sources == ["A", "B"]


def test_fill_missing_with_nothing_useful_keeps_sources():
    entry = make_entry()
    assert entry.fill_missing_from(make_entry(sources=["B"])) is entry


def test_dict_round_trip():
    entry = make_entry(synonyms=["fleeting"], audio_url="https://example.com/a.mp3")
    assert WordEntry.from_dict(entry.to_dict()) == entry
